"""Basic Pitch note transcription on ONNX Runtime.

Basic Pitch (Spotify, Apache-2.0) is a small polyphonic pitch model. The
``basic-pitch`` package pins TensorFlow < 2.15.1, which has no wheels for
Python 3.12+, so this module runs the ONNX export shipped inside that package
(``assets/models/basic-pitch-nmp.onnx``, from basic-pitch 0.4.0) and ports
the windowing from ``inference.py`` and the note decoder from
``note_creation.py``. Pitch bends are not ported. Places that differ from
upstream say so in a comment starting with "Upstream:".
"""

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from runtime_tools import resource_path

MODEL_PATH = resource_path("assets/models/basic-pitch-nmp.onnx")
MODEL_SHA256 = "2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec"

SAMPLE_RATE = 22_050
FFT_HOP = 256
WINDOW_SAMPLES = 2 * SAMPLE_RATE - FFT_HOP  # model input length
WINDOW_FRAMES = 172  # model output frames per window
OVERLAP_FRAMES = 30  # half is trimmed from each side of every window
WINDOW_STEP = WINDOW_SAMPLES - OVERLAP_FRAMES * FFT_HOP
FRAMES_PER_STEP = WINDOW_FRAMES - OVERLAP_FRAMES  # frames each window keeps
MIDI_OFFSET = 21  # MIDI number of the lowest pitch bin (A0)
N_PITCHES = 88

_INPUT = "serving_default_input_2:0"
_OUTPUTS = {  # names in the ONNX graph
    "note": "StatefulPartitionedCall:1",
    "onset": "StatefulPartitionedCall:2",
    "contour": "StatefulPartitionedCall:0",
}


@dataclass(frozen=True)
class Activations:
    note: np.ndarray  # (frames, 88), frame activation per semitone
    onset: np.ndarray  # (frames, 88)
    contour: np.ndarray  # (frames, 264), thirds of a semitone
    times: np.ndarray  # (frames,), seconds; not evenly spaced


class Note(NamedTuple):
    onset: float  # seconds
    offset: float
    pitch: int  # MIDI, sounding
    score: float  # mean frame activation over the note; uncalibrated
    start_frame: int
    end_frame: int


def load_session(path=MODEL_PATH):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.log_severity_level = 3
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def to_model_input(audio: np.ndarray, sr: int) -> np.ndarray:
    """Mono float32 at the model's sample rate."""
    mono = audio.mean(axis=1) if audio.ndim == 2 else audio
    mono = np.ascontiguousarray(mono, dtype=np.float32)
    if sr != SAMPLE_RATE:
        import soxr

        mono = soxr.resample(mono, sr, SAMPLE_RATE, quality="HQ").astype(np.float32)
    return mono


def infer(audio: np.ndarray, sr: int, session=None, batch_size: int = 16) -> Activations:
    """Run the model over ``audio`` (mono or (frames, channels)) at any rate."""
    if session is None:
        session = load_session()
    mono = to_model_input(audio, sr)
    padded = np.concatenate([np.zeros(OVERLAP_FRAMES * FFT_HOP // 2, np.float32), mono])
    starts = range(0, len(padded), WINDOW_STEP)
    windows = np.zeros((len(starts), WINDOW_SAMPLES, 1), dtype=np.float32)
    for i, start in enumerate(starts):
        chunk = padded[start : start + WINDOW_SAMPLES]
        windows[i, : len(chunk), 0] = chunk

    outputs = {name: [] for name in _OUTPUTS}
    for b in range(0, len(windows), batch_size):
        results = session.run(list(_OUTPUTS.values()), {_INPUT: windows[b : b + batch_size]})
        for name, result in zip(_OUTPUTS, results):
            outputs[name].append(result)

    trim = OVERLAP_FRAMES // 2
    n_frames = _frames_covering(len(mono))
    unwrapped = {}
    for name, chunks in outputs.items():
        stacked = np.concatenate(chunks)[:, trim:-trim, :]
        unwrapped[name] = stacked.reshape(-1, stacked.shape[-1])[:n_frames]
    return Activations(
        note=unwrapped["note"],
        onset=unwrapped["onset"],
        contour=unwrapped["contour"],
        times=frame_times(n_frames),
    )


def _frames_covering(n_samples: int) -> int:
    # Upstream: trims to floor(n_samples * 86 / 22050) frames, but unwrapped
    # frames advance FRAMES_PER_STEP per WINDOW_STEP samples (~86.6 fps), so
    # the last ~0.7 % of the audio was never transcribed (2 s of 5 minutes).
    full, rest = divmod(n_samples, WINDOW_STEP)
    return full * FRAMES_PER_STEP + min(-(-rest // FFT_HOP), FRAMES_PER_STEP)


def frame_times(n_frames: int) -> np.ndarray:
    """Time of each output frame, in seconds.

    Frames are one hop apart inside a window, and each window starts
    WINDOW_STEP samples after the previous one, so the grid is not uniform.
    Upstream: ``model_frames_to_time`` approximates this with a correction
    every 172 frames plus a 1.8 ms "magic number", which leaves a ±8 ms
    sawtooth error.
    """
    window, frame = np.divmod(np.arange(n_frames), FRAMES_PER_STEP)
    return (window * WINDOW_STEP + frame * FFT_HOP) / SAMPLE_RATE


def extract_notes(
    act: Activations,
    onset_threshold: float = 0.5,
    frame_threshold: float = 0.3,
    min_frames: int = 11,
    infer_onsets: bool = True,
    melodia: bool = True,
    neighbor_suppression: bool = True,
    energy_tol: int = 11,
    min_pitch: int | None = None,
    max_pitch: int | None = None,
) -> list[Note]:
    """Decode activations into notes (upstream ``output_to_notes_polyphonic``).

    Defaults are upstream's. A note must last more than ``min_frames`` frames
    (11 frames is ~128 ms). ``neighbor_suppression`` is upstream's behavior of
    clearing the semitones next to each decoded note for its whole duration;
    when two notes a semitone apart sound together, the one decoded second is
    dropped.
    """
    frames = act.note.copy()
    onsets = act.onset.copy()
    n_frames = frames.shape[0]
    if n_frames == 0:
        return []

    if max_pitch is not None:
        frames[:, max_pitch - MIDI_OFFSET + 1 :] = 0
        onsets[:, max_pitch - MIDI_OFFSET + 1 :] = 0
    if min_pitch is not None:
        frames[:, : max(min_pitch - MIDI_OFFSET, 0)] = 0
        onsets[:, : max(min_pitch - MIDI_OFFSET, 0)] = 0
    if infer_onsets:
        onsets = _inferred_onsets(onsets, frames)

    from scipy.signal import argrelmax

    peaks = np.zeros(onsets.shape)
    peak_idx = argrelmax(onsets, axis=0)
    peaks[peak_idx] = onsets[peak_idx]
    onset_time_idx, onset_freq_idx = np.where(peaks >= onset_threshold)
    # Backwards in time; at the same frame, higher pitches first.
    onset_time_idx = onset_time_idx[::-1]
    onset_freq_idx = onset_freq_idx[::-1]

    remaining = frames.copy()
    events: list[tuple[int, int, int, float]] = []

    def clear(start: int, end: int, freq: int):
        remaining[start:end, freq] = 0
        if neighbor_suppression:
            if freq < N_PITCHES - 1:
                remaining[start:end, freq + 1] = 0
            if freq > 0:
                remaining[start:end, freq - 1] = 0

    for start, freq in zip(onset_time_idx, onset_freq_idx):
        if start >= n_frames - 1:
            continue
        i = start + 1
        k = 0  # frames since energy dropped below threshold
        while i < n_frames - 1 and k < energy_tol:
            k = k + 1 if remaining[i, freq] < frame_threshold else 0
            i += 1
        i -= k
        if i - start <= min_frames:
            continue
        clear(start, i, freq)
        events.append((start, i, freq, float(np.mean(frames[start:i, freq]))))

    if melodia:
        # Notes without a detected onset, grown from the strongest leftover
        # energy forwards and backwards.
        while np.max(remaining) > frame_threshold:
            mid, freq = np.unravel_index(np.argmax(remaining), remaining.shape)
            remaining[mid, freq] = 0

            i = mid + 1
            k = 0
            while i < n_frames - 1 and k < energy_tol:
                k = k + 1 if remaining[i, freq] < frame_threshold else 0
                clear(i, i + 1, freq)
                i += 1
            end = i - 1 - k

            i = mid - 1
            k = 0
            while i > 0 and k < energy_tol:
                k = k + 1 if remaining[i, freq] < frame_threshold else 0
                clear(i, i + 1, freq)
                i -= 1
            start = i + 1 + k

            if end - start <= min_frames:
                continue
            events.append((start, end, freq, float(np.mean(frames[start:end, freq]))))

    times = act.times
    return [
        Note(float(times[s]), float(times[e]), int(f) + MIDI_OFFSET, a, int(s), int(e))
        for s, e, f, a in events
    ]


def _inferred_onsets(onsets: np.ndarray, frames: np.ndarray, n_diff: int = 2) -> np.ndarray:
    """Add onsets where frame activation jumps (upstream ``get_infered_onsets``)."""
    diffs = []
    for n in range(1, n_diff + 1):
        shifted = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(shifted[n:, :] - shifted[:-n, :])
    frame_diff = np.min(diffs, axis=0)
    frame_diff[frame_diff < 0] = 0
    frame_diff[:n_diff, :] = 0
    peak = np.max(frame_diff)
    # Upstream: divides by the peak unguarded, which yields NaN on silence.
    if peak > 0:
        frame_diff = np.max(onsets) * frame_diff / peak
    return np.maximum(onsets, frame_diff)
