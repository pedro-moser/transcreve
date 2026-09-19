import 'dart:async';
import 'dart:io';
import 'package:just_audio/just_audio.dart';

class AudioService {
  final AudioPlayer _player = AudioPlayer();

  Stream<Duration> get positionStream => _player.positionStream;
  Stream<PlayerState> get playerStateStream => _player.playerStateStream;
  Stream<Duration?> get durationStream => _player.durationStream;

  bool get isPlaying => _player.playing;
  Duration get position => _player.position;
  Duration? get duration => _player.duration;
  double get speed => _player.speed;

  // Loop A-B points
  Duration? loopStart;
  Duration? loopEnd;
  bool loopEnabled = false;

  // Cue point — play always restarts from here
  Duration? cuePoint;

  StreamSubscription<Duration>? _loopSub;

  Future<void> load(String filePath) async {
    await _player.stop();
    await _player.setFilePath(filePath);
    _setupLoop();
  }

  void _setupLoop() {
    _loopSub?.cancel();
    _loopSub = _player.positionStream.listen((pos) {
      if (loopEnabled && loopStart != null && loopEnd != null) {
        if (pos >= loopEnd!) {
          _player.seek(loopStart!);
        }
      }
    });
  }

  Future<void> play() async {
    if (cuePoint != null) {
      await _player.seek(cuePoint!);
    } else if (loopEnabled && loopStart != null) {
      final pos = _player.position;
      if (loopEnd != null && pos >= loopEnd!) {
        await _player.seek(loopStart!);
      }
    }
    await _player.play();
  }

  Future<void> pause() async => _player.pause();

  Future<void> togglePlay() async {
    if (_player.playing) {
      await pause();
    } else {
      await play();
    }
  }

  Future<void> seek(Duration position) async {
    await _player.seek(position);
  }

  Future<void> seekRelative(Duration delta) async {
    final newPos = _player.position + delta;
    final dur = _player.duration;
    if (dur != null) {
      final clamped = newPos.isNegative
          ? Duration.zero
          : newPos > dur
              ? dur
              : newPos;
      await _player.seek(clamped);
    }
  }

  Future<void> setSpeed(double speed) async {
    final clamped = speed.clamp(0.25, 2.0);
    await _player.setSpeed(clamped);
  }

  Future<void> adjustSpeed(double delta) async {
    await setSpeed(_player.speed + delta);
  }

  void setLoopStart(Duration? pos) {
    loopStart = pos ?? _player.position;
  }

  void setLoopEnd(Duration? pos) {
    loopEnd = pos ?? _player.position;
  }

  void toggleLoop() {
    loopEnabled = !loopEnabled;
  }

  void setCuePoint() {
    cuePoint = _player.position;
  }

  void clearCuePoint() {
    cuePoint = null;
  }

  void clearLoop() {
    loopStart = null;
    loopEnd = null;
    loopEnabled = false;
  }

  Future<int> getDurationMs(String filePath) async {
    // Use ffprobe to get duration
    final result = await Process.run('ffprobe', [
      '-v', 'quiet',
      '-print_format', 'csv',
      '-show_entries', 'format=duration',
      filePath,
    ]);
    if (result.exitCode == 0) {
      final output = (result.stdout as String).trim();
      final parts = output.split(',');
      if (parts.length >= 2) {
        final seconds = double.tryParse(parts[1]);
        if (seconds != null) return (seconds * 1000).round();
      }
    }
    return 0;
  }

  Future<void> dispose() async {
    _loopSub?.cancel();
    await _player.dispose();
  }
}
