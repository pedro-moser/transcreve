import 'package:flutter/material.dart';
import '../models/section.dart';

class SeekbarPainter extends CustomPainter {
  final Duration position;
  final Duration duration;
  final Duration? loopStart;
  final Duration? loopEnd;
  final bool loopEnabled;
  final List<Section> sections;
  final Duration? cuePoint;

  SeekbarPainter({
    required this.position,
    required this.duration,
    this.loopStart,
    this.loopEnd,
    this.loopEnabled = false,
    this.sections = const [],
    this.cuePoint,
  });

  double _fraction(Duration d) {
    if (duration.inMilliseconds == 0) return 0;
    return d.inMilliseconds / duration.inMilliseconds;
  }

  @override
  void paint(Canvas canvas, Size size) {
    final trackH = 8.0;
    final markerH = size.height;
    final trackY = size.height / 2 - trackH / 2;

    // Background track
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromLTWH(0, trackY, size.width, trackH),
        const Radius.circular(4),
      ),
      Paint()..color = const Color(0xFF45475A),
    );

    // Loop region
    if (loopEnabled && loopStart != null && loopEnd != null) {
      final x1 = _fraction(loopStart!) * size.width;
      final x2 = _fraction(loopEnd!) * size.width;
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(x1, trackY, x2 - x1, trackH),
          const Radius.circular(4),
        ),
        Paint()..color = const Color(0xFFFAB387).withAlpha(100),
      );
    }

    // Progress
    final progressW = _fraction(position) * size.width;
    if (progressW > 0) {
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(0, trackY, progressW, trackH),
          const Radius.circular(4),
        ),
        Paint()..color = const Color(0xFF89B4FA),
      );
    }

    // Section markers
    for (final section in sections) {
      final x = _fraction(Duration(milliseconds: section.startMs)) * size.width;
      final color = Color(section.colorValue);
      canvas.drawRect(
        Rect.fromLTWH(x - 1, 0, 2, markerH),
        Paint()..color = color,
      );
      // Triangle at top
      final path = Path()
        ..moveTo(x - 5, 0)
        ..lineTo(x + 5, 0)
        ..lineTo(x, 8)
        ..close();
      canvas.drawPath(path, Paint()..color = color);
    }

    // Loop start/end markers
    if (loopStart != null) {
      final x = _fraction(loopStart!) * size.width;
      canvas.drawRect(
        Rect.fromLTWH(x - 1.5, trackY - 4, 3, trackH + 8),
        Paint()..color = const Color(0xFFFAB387),
      );
    }
    if (loopEnd != null) {
      final x = _fraction(loopEnd!) * size.width;
      canvas.drawRect(
        Rect.fromLTWH(x - 1.5, trackY - 4, 3, trackH + 8),
        Paint()..color = const Color(0xFFFAB387),
      );
    }

    // Cue point marker (diamond shape)
    if (cuePoint != null) {
      final cx = _fraction(cuePoint!) * size.width;
      const cueColor = Color(0xFF94E2D5);
      final path = Path()
        ..moveTo(cx, trackY - 6)
        ..lineTo(cx + 5, size.height / 2)
        ..lineTo(cx, size.height / 2 + 6)
        ..lineTo(cx - 5, size.height / 2)
        ..close();
      canvas.drawPath(path, Paint()..color = cueColor);
      canvas.drawRect(
        Rect.fromLTWH(cx - 1, trackY - 6, 2, trackH + 12),
        Paint()..color = cueColor.withAlpha(120),
      );
    }

    // Playhead
    final px = _fraction(position) * size.width;
    canvas.drawCircle(
      Offset(px, size.height / 2),
      8,
      Paint()..color = Colors.white,
    );
  }

  @override
  bool shouldRepaint(SeekbarPainter old) =>
      old.position != position ||
      old.duration != duration ||
      old.loopStart != loopStart ||
      old.loopEnd != loopEnd ||
      old.loopEnabled != loopEnabled ||
      old.sections.length != sections.length ||
      old.cuePoint != cuePoint;
}
