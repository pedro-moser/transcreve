import threading

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, QThread, QTimer, Signal


# seconds of audio to pre-stretch per chunk
CHUNK_SECS = 20


class _StretchWorker(QObject):
    """Runs pyrubberband on a chunk in a background thread."""
    finished = Signal(object, float, int)  # data, speed, start_frame

    def __init__(self, data: np.ndarray, sr: int, speed: float, start_frame: int):
        super().__init__()
        self._data = data
        self._sr = sr
        self._speed = speed
        self._start_frame = start_frame

    def run(self):
        try:
            import pyrubberband as pyrb
            result = pyrb.time_stretch(self._data, self._sr, self._speed).astype(np.float32)
            self.finished.emit(result, self._speed, self._start_frame)
        except Exception:
            self.finished.emit(None, self._speed, self._start_frame)


class _LoadWorker(QObject):
    """Loads audio file in background thread."""
    finished = Signal(object, int)  # (data, sr) or (None, 0) on error
    error = Signal(str)

    def __init__(self, file_path: str):
        super().__init__()
        self._path = file_path

    def run(self):
        try:
            data, sr = sf.read(self._path, dtype="float32", always_2d=True)
            self.finished.emit(data, sr)
        except Exception as e:
            self.error.emit(str(e))


class AudioService(QObject):
    position_changed = Signal(int)   # ms
    duration_changed = Signal(int)   # ms
    playing_changed = Signal(bool)
    loading_changed = Signal(bool)   # True=loading, False=ready
    error_occurred = Signal(str)

    BLOCK_SIZE = 2048

    def __init__(self, parent=None):
        super().__init__(parent)

        # audio data
        self._data: np.ndarray | None = None
        self._sr: int = 44100
        self._channels: int = 2
        self._total_frames: int = 0

        # playback state
        self._pos: float = 0.0
        self._playing: bool = False
        self._speed: float = 1.0
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()

        # rubberband chunk cache
        self._rb_buf: np.ndarray | None = None    # current stretched chunk
        self._rb_speed: float = 1.0
        self._rb_start: int = 0                    # original start frame of chunk
        self._rb_end: int = 0                      # original end frame of chunk
        self._rb_thread: QThread | None = None
        self._rb_worker: _StretchWorker | None = None
        self._rb_pending: bool = False

        # file loading
        self._load_thread: QThread | None = None
        self._load_worker: _LoadWorker | None = None

        # stems
        self._stems: dict[str, np.ndarray] | None = None
        self._stem_muted: dict[str, bool] = {}
        self._mix_cache: np.ndarray | None = None  # cached mixed stems

        # loop
        self.loop_start: int | None = None
        self.loop_end: int | None = None
        self.loop_enabled: bool = False

        # cue point
        self.cue_point: int | None = None

        # position timer
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._emit_position)

    # --- properties ---

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def position_ms(self) -> int:
        if self._data is None:
            return 0
        return int(self._pos / self._sr * 1000)

    @property
    def duration_ms(self) -> int:
        if self._data is None:
            return 0
        return int(self._total_frames / self._sr * 1000)

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def sample_rate(self) -> int:
        return self._sr

    @property
    def audio_data(self) -> np.ndarray | None:
        return self._data

    # --- load (async) ---

    def load(self, file_path: str):
        self.stop()
        self._cancel_rb()
        self._cancel_load()
        self._data = None
        self._rb_buf = None
        self.loading_changed.emit(True)

        self._load_thread = QThread()
        self._load_worker = _LoadWorker(file_path)
        self._load_worker.moveToThread(self._load_thread)
        self._load_thread.started.connect(self._load_worker.run)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.error.connect(self._on_load_error)
        self._load_thread.start()

    def _on_load_finished(self, data, sr: int):
        self._cleanup_load_thread()
        if data is None:
            self.loading_changed.emit(False)
            return
        self._data = data
        self._sr = sr
        self._channels = data.shape[1]
        self._total_frames = data.shape[0]
        self._pos = 0.0
        self.duration_changed.emit(self.duration_ms)
        self.position_changed.emit(0)
        self.loading_changed.emit(False)

    def _on_load_error(self, msg: str):
        self._cleanup_load_thread()
        self.error_occurred.emit(f"Erro ao abrir arquivo: {msg}")
        self.loading_changed.emit(False)

    def _cancel_load(self):
        if self._load_thread and self._load_thread.isRunning():
            self._load_thread.quit()
            self._load_thread.wait()
        self._load_thread = None
        self._load_worker = None

    def _cleanup_load_thread(self):
        if self._load_thread:
            self._load_thread.quit()
            self._load_thread.wait()
            self._load_thread = None
            self._load_worker = None

    # --- playback ---

    def play(self):
        if self._data is None or self._playing:
            return
        if self.cue_point is not None:
            self.seek(self.cue_point)
        elif self.loop_enabled and self.loop_start is not None:
            if self.loop_end is not None and self.position_ms >= self.loop_end:
                self.seek(self.loop_start)

        # pre-stretch chunk from current position before playing
        self._ensure_rb_chunk()

        self._playing = True
        self._open_stream()
        self._timer.start()
        self.playing_changed.emit(True)

    def pause(self):
        if not self._playing:
            return
        self._playing = False
        self._close_stream()
        self._timer.stop()
        self.playing_changed.emit(False)

    def toggle_play(self):
        if self._playing:
            self.pause()
        else:
            self.play()

    def stop(self):
        self.pause()
        self._pos = 0.0
        self.position_changed.emit(0)

    # --- seek ---

    def seek(self, ms: int):
        if self._data is None:
            return
        ms = max(0, min(ms, self.duration_ms))
        with self._lock:
            self._pos = ms / 1000.0 * self._sr
        self.position_changed.emit(ms)

    def seek_relative(self, delta_ms: int):
        self.seek(self.position_ms + delta_ms)

    # --- speed ---

    def set_speed(self, speed: float):
        speed = round(max(0.25, min(2.0, speed)), 2)
        if speed == self._speed:
            return
        if abs(speed - 1.0) < 0.01:
            # back to 1.0x — clear rb, direct playback
            with self._lock:
                self._speed = speed
                self._rb_buf = None
        else:
            # build bridge BEFORE updating self._speed
            # so callback keeps using old buffer until swap
            self._stretch_bridge(speed)
            # now atomically set speed + buffer together
            # (already done inside _stretch_bridge)
            self._ensure_rb_chunk()

    def adjust_speed(self, delta: float):
        self.set_speed(self._speed + delta)

    # --- loop ---

    def set_loop_start(self, ms: int | None = None):
        self.loop_start = ms if ms is not None else self.position_ms

    def set_loop_end(self, ms: int | None = None):
        self.loop_end = ms if ms is not None else self.position_ms

    def toggle_loop(self):
        self.loop_enabled = not self.loop_enabled

    def clear_loop(self):
        self.loop_start = None
        self.loop_end = None
        self.loop_enabled = False

    # --- cue point ---

    def set_cue_point(self):
        self.cue_point = self.position_ms

    def clear_cue_point(self):
        self.cue_point = None

    # --- stems ---

    def load_stems(self, stems: dict[str, np.ndarray]):
        with self._lock:
            self._stems = stems
            self._stem_muted = {name: False for name in stems}
            self._rebuild_mix()
            # invalidate rb cache so it uses the new mix
            self._rb_buf = None

    def toggle_stem(self, name: str):
        if self._stems is None or name not in self._stem_muted:
            return
        with self._lock:
            self._stem_muted[name] = not self._stem_muted[name]
            self._rebuild_mix()
            self._rb_buf = None

    def solo_stem(self, name: str):
        if self._stems is None:
            return
        with self._lock:
            for n in self._stem_muted:
                self._stem_muted[n] = (n != name)
            self._rebuild_mix()
            self._rb_buf = None

    def unsolo_all(self):
        if self._stems is None:
            return
        with self._lock:
            for n in self._stem_muted:
                self._stem_muted[n] = False
            self._rebuild_mix()
            self._rb_buf = None

    def is_stem_muted(self, name: str) -> bool:
        return self._stem_muted.get(name, False)

    @property
    def has_stems(self) -> bool:
        return self._stems is not None

    def _rebuild_mix(self):
        """Rebuild the active mix from unmuted stems."""
        if self._stems is None:
            self._mix_cache = None
            return
        active = [data for name, data in self._stems.items() if not self._stem_muted.get(name, False)]
        if active:
            self._mix_cache = sum(active)
        else:
            # all muted: silence
            first = next(iter(self._stems.values()))
            self._mix_cache = np.zeros_like(first)

    @property
    def _playback_data(self) -> np.ndarray | None:
        """Return the audio data to use for playback (mix or original)."""
        if self._mix_cache is not None:
            return self._mix_cache
        return self._data

    # --- stream ---

    def _open_stream(self):
        self._close_stream()
        self._stream = sd.OutputStream(
            samplerate=self._sr,
            channels=self._channels,
            blocksize=self.BLOCK_SIZE,
            dtype="float32",
            callback=self._audio_callback,
        )
        self._stream.start()

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status):
        with self._lock:
            if self._data is None:
                outdata[:] = 0
                return

            speed = self._speed
            pos = self._pos

            # loop check
            current_ms = int(pos / self._sr * 1000)
            if self.loop_enabled and self.loop_end is not None and current_ms >= self.loop_end:
                if self.loop_start is not None:
                    pos = self.loop_start / 1000.0 * self._sr
                    self._pos = pos

            if abs(speed - 1.0) < 0.01:
                # 1.0x: direct copy
                self._fill_direct(outdata, frames, pos)
            elif self._rb_buf is not None and abs(self._rb_speed - speed) < 0.01:
                # have matching rubberband chunk
                ipos = int(pos)
                if self._rb_start <= ipos < self._rb_end:
                    self._fill_from_rb(outdata, frames, pos, speed)
                else:
                    self._fill_interpolated(outdata, frames, pos, speed)
            else:
                self._fill_interpolated(outdata, frames, pos, speed)

    def _fill_direct(self, outdata: np.ndarray, frames: int, pos: float):
        """1.0x speed: direct copy."""
        data = self._playback_data
        ipos = int(pos)
        end = ipos + frames
        total = self._total_frames
        if end <= total:
            outdata[:] = data[ipos:end]
            self._pos = float(end)
        else:
            avail = max(0, total - ipos)
            if avail > 0:
                outdata[:avail] = data[ipos:ipos + avail]
            outdata[avail:] = 0
            self._pos = float(total)
            self._playing = False

    def _fill_from_rb(self, outdata: np.ndarray, frames: int, pos: float, speed: float):
        """Fill from rubberband pre-stretched chunk."""
        rb = self._rb_buf
        # offset within rb buffer
        orig_offset = int(pos) - self._rb_start
        rb_pos = int(orig_offset / speed)
        rb_end = rb_pos + frames

        if rb_pos < 0:
            rb_pos = 0
            rb_end = frames

        if rb_end <= len(rb) and rb_pos >= 0:
            outdata[:] = rb[rb_pos:rb_end]
            # update position in original frames
            self._pos = self._rb_start + (rb_pos + frames) * speed
        else:
            # past chunk boundary — fallback to interpolation
            self._fill_interpolated(outdata, frames, pos, speed)

    def _fill_interpolated(self, outdata: np.ndarray, frames: int, pos: float, speed: float):
        """Linear interpolation — instant but changes pitch."""
        data = self._playback_data
        total = self._total_frames
        channels = self._channels
        indices = pos + np.arange(frames, dtype=np.float64) * speed
        end_pos = pos + frames * speed

        if end_pos >= total - 1:
            valid_mask = indices < (total - 1)
            n_valid = int(np.sum(valid_mask))
            if n_valid > 0:
                idx = indices[:n_valid]
                i0 = idx.astype(np.int64)
                np.clip(i0, 0, total - 2, out=i0)
                frac = (idx - i0).astype(np.float32)
                if channels > 1:
                    frac = frac[:, np.newaxis]
                outdata[:n_valid] = data[i0] * (1 - frac) + data[i0 + 1] * frac
            outdata[n_valid:] = 0
            self._pos = float(total)
            self._playing = False
        else:
            i0 = indices.astype(np.int64)
            np.clip(i0, 0, total - 2, out=i0)
            frac = (indices - i0).astype(np.float32)
            if channels > 1:
                frac = frac[:, np.newaxis]
            outdata[:] = data[i0] * (1 - frac) + data[i0 + 1] * frac
            self._pos = end_pos

    # --- rubberband chunk pipeline ---

    BRIDGE_SECS = 2  # small sync chunk for instant pitch-correct playback

    def _stretch_bridge(self, new_speed: float):
        """Synchronously stretch a tiny chunk, then atomically swap speed+buffer."""
        if self._data is None:
            self._speed = new_speed
            return
        try:
            import pyrubberband as pyrb
            start = int(self._pos)
            end = min(start + self._sr * self.BRIDGE_SECS, self._total_frames)
            if start >= end:
                self._speed = new_speed
                return
            pdata = self._playback_data
            if pdata is None:
                self._speed = new_speed
                return
            chunk = pdata[start:end]
            stretched = pyrb.time_stretch(chunk, self._sr, new_speed).astype(np.float32)
            with self._lock:
                # atomic swap: speed + buffer change together
                self._speed = new_speed
                self._rb_buf = stretched
                self._rb_speed = new_speed
                self._rb_start = start
                self._rb_end = end
        except Exception:
            self._speed = new_speed

    def _ensure_rb_chunk(self):
        """Request a rubberband chunk from current position if needed."""
        if self._data is None or abs(self._speed - 1.0) < 0.01:
            return
        ipos = int(self._pos)
        # check if current chunk covers our position with enough runway
        if (self._rb_buf is not None
                and abs(self._rb_speed - self._speed) < 0.01
                and self._rb_start <= ipos < self._rb_end):
            remaining_secs = (self._rb_end - ipos) / self._sr
            if remaining_secs < 5:
                # prefetch next chunk AFTER current one (don't overwrite current)
                self._request_rb_chunk(self._rb_end, extend=True)
            return
        # no coverage — request from current position
        self._request_rb_chunk(ipos, extend=False)

    def _request_rb_chunk(self, start_frame: int, extend: bool = False):
        if self._data is None:
            return
        if self._rb_thread is not None and self._rb_thread.isRunning():
            self._rb_pending = True
            return

        end_frame = min(start_frame + self._sr * CHUNK_SECS, self._total_frames)
        if start_frame >= end_frame:
            return
        pdata = self._playback_data
        if pdata is None:
            return
        chunk = pdata[start_frame:end_frame]
        self._rb_extend = extend

        self._rb_thread = QThread()
        self._rb_worker = _StretchWorker(chunk, self._sr, self._speed, start_frame)
        self._rb_worker.moveToThread(self._rb_thread)
        self._rb_thread.started.connect(self._rb_worker.run)
        self._rb_worker.finished.connect(self._on_rb_finished)
        self._rb_thread.start()

    def _on_rb_finished(self, result, speed: float, start_frame: int):
        if self._rb_thread:
            self._rb_thread.quit()
            self._rb_thread.wait()
            self._rb_thread = None
            self._rb_worker = None

        extend = getattr(self, '_rb_extend', False)
        if result is not None and abs(speed - self._speed) < 0.01:
            with self._lock:
                if extend and self._rb_buf is not None and self._rb_start < start_frame:
                    # append to existing buffer instead of replacing
                    self._rb_buf = np.concatenate([self._rb_buf, result])
                    self._rb_end = start_frame + self._sr * CHUNK_SECS
                else:
                    self._rb_buf = result
                    self._rb_speed = speed
                    self._rb_start = start_frame
                    self._rb_end = start_frame + self._sr * CHUNK_SECS

        # process pending or prefetch next chunk
        if self._rb_pending:
            self._rb_pending = False
            self._ensure_rb_chunk()
        elif self._data is not None and abs(speed - self._speed) < 0.01:
            next_start = start_frame + self._sr * CHUNK_SECS
            if next_start < self._total_frames:
                self._request_rb_chunk(next_start, extend=True)

    def _cancel_rb(self):
        self._rb_pending = False
        if self._rb_thread and self._rb_thread.isRunning():
            self._rb_thread.quit()
            self._rb_thread.wait()
        self._rb_thread = None
        self._rb_worker = None

    # --- timer ---

    def _emit_position(self):
        ms = self.position_ms
        self.position_changed.emit(ms)
        if self._playing and self._pos >= self._total_frames:
            self.pause()
        # check if we need more rb chunks
        if self._playing and abs(self._speed - 1.0) >= 0.01:
            self._ensure_rb_chunk()

    # --- cleanup ---

    def dispose(self):
        self.stop()
        self._cancel_rb()
        self._cancel_load()
        self._timer.stop()
        self._data = None
        self._rb_buf = None
