import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:just_audio/just_audio.dart';
import 'package:uuid/uuid.dart';
import '../models/song.dart';
import '../models/section.dart';
import '../services/audio_service.dart';
import '../services/storage_service.dart';
import '../widgets/seekbar_painter.dart';

class PlayerScreen extends StatefulWidget {
  final Song song;
  const PlayerScreen({super.key, required this.song});

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  final AudioService _audio = AudioService();
  late Song _song;

  Duration _position = Duration.zero;
  Duration _duration = Duration.zero;
  bool _isPlaying = false;
  double _speed = 1.0;

  Duration? _cuePoint;

  bool _loopEnabled = false;
  Duration? _loopStart;
  Duration? _loopEnd;

  bool _isDragging = false;
  double _dragValue = 0;

  Section? _selectedSection;
  final _notesController = TextEditingController();
  final _sectionNotesController = TextEditingController();
  bool _showSections = true;

  final FocusNode _focusNode = FocusNode();
  final List<StreamSubscription> _subs = [];

  static const _sectionColors = [
    0xFF89B4FA, // blue
    0xFFA6E3A1, // green
    0xFFFAB387, // peach
    0xFFCBA6F7, // mauve
    0xFFF38BA8, // red
    0xFF94E2D5, // teal
    0xFFF9E2AF, // yellow
  ];

  @override
  void initState() {
    super.initState();
    _song = widget.song;
    _notesController.text = _song.notes;
    _initAudio();
  }

  Future<void> _initAudio() async {
    await _audio.load(_song.filePath);
    _subs.add(_audio.positionStream.listen((pos) {
      if (!_isDragging && mounted) {
        setState(() => _position = pos);
      }
    }));
    _subs.add(_audio.durationStream.listen((dur) {
      if (dur != null && mounted) setState(() => _duration = dur);
    }));
    _subs.add(_audio.playerStateStream.listen((state) {
      if (mounted) setState(() => _isPlaying = state.playing);
    }));
    _focusNode.requestFocus();
  }

  Future<void> _save() async {
    _song.notes = _notesController.text;
    await StorageService.saveSong(_song);
  }

  void _setSpeed(double s) {
    _audio.setSpeed(s);
    setState(() => _speed = s.clamp(0.25, 2.0));
  }

  void _toggleLoop() {
    _audio.toggleLoop();
    setState(() {
      _loopEnabled = _audio.loopEnabled;
      _loopStart = _audio.loopStart;
      _loopEnd = _audio.loopEnd;
    });
  }

  void _setLoopStart() {
    _audio.setLoopStart(_position);
    setState(() {
      _loopStart = _audio.loopStart;
      _loopEnabled = _audio.loopStart != null && _audio.loopEnd != null;
      _audio.loopEnabled = _loopEnabled;
    });
  }

  void _setLoopEnd() {
    _audio.setLoopEnd(_position);
    setState(() {
      _loopEnd = _audio.loopEnd;
      _loopEnabled = _audio.loopStart != null && _audio.loopEnd != null;
      _audio.loopEnabled = _loopEnabled;
    });
  }

  void _setCuePoint() {
    _audio.setCuePoint();
    setState(() => _cuePoint = _audio.cuePoint);
  }

  void _clearCuePoint() {
    _audio.clearCuePoint();
    setState(() => _cuePoint = null);
  }

  void _clearLoop() {
    _audio.clearLoop();
    setState(() {
      _loopStart = null;
      _loopEnd = null;
      _loopEnabled = false;
    });
  }

  void _addSection() {
    final colorIdx = _song.sections.length % _sectionColors.length;
    final section = Section(
      id: const Uuid().v4(),
      name: 'Seção ${_song.sections.length + 1}',
      startMs: _position.inMilliseconds,
      colorValue: _sectionColors[colorIdx],
    );
    setState(() {
      _song.sections.add(section);
      _song.sections.sort((a, b) => a.startMs.compareTo(b.startMs));
      _selectedSection = section;
      _sectionNotesController.text = section.notes;
    });
    _save();
  }

  void _deleteSection(Section section) {
    setState(() {
      _song.sections.remove(section);
      if (_selectedSection == section) {
        _selectedSection = null;
        _sectionNotesController.clear();
      }
    });
    _save();
  }

  void _renameSection(Section section) async {
    final ctrl = TextEditingController(text: section.name);
    final newName = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E2E),
        title: const Text('Renomear seção',
            style: TextStyle(color: Colors.white)),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            enabledBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: Colors.white24)),
            focusedBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: Color(0xFF89B4FA))),
          ),
          onSubmitted: (v) => Navigator.of(ctx).pop(v),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(null),
              child: const Text('Cancelar',
                  style: TextStyle(color: Colors.white54))),
          TextButton(
              onPressed: () => Navigator.of(ctx).pop(ctrl.text),
              child: const Text('OK',
                  style: TextStyle(color: Color(0xFF89B4FA)))),
        ],
      ),
    );
    if (newName != null && newName.isNotEmpty) {
      setState(() => section.name = newName);
      _save();
    }
    _focusNode.requestFocus();
  }

  void _seekToSection(Section section) {
    _audio.seek(Duration(milliseconds: section.startMs));
    setState(() {
      _selectedSection = section;
      _sectionNotesController.text = section.notes;
    });
  }

  void _seekToPrevSection() {
    final sorted = [..._song.sections]
      ..sort((a, b) => a.startMs.compareTo(b.startMs));
    final current = _position.inMilliseconds;
    Section? target;
    for (final s in sorted.reversed) {
      if (s.startMs < current - 500) {
        target = s;
        break;
      }
    }
    if (target != null) _seekToSection(target);
  }

  void _seekToNextSection() {
    final sorted = [..._song.sections]
      ..sort((a, b) => a.startMs.compareTo(b.startMs));
    final current = _position.inMilliseconds;
    Section? target;
    for (final s in sorted) {
      if (s.startMs > current + 100) {
        target = s;
        break;
      }
    }
    if (target != null) _seekToSection(target);
  }

  KeyEventResult _handleKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent && event is! KeyRepeatEvent) {
      return KeyEventResult.ignored;
    }
    final key = event.logicalKey;
    final ctrl = HardwareKeyboard.instance.isControlPressed;

    if (key == LogicalKeyboardKey.space) {
      _audio.togglePlay();
      return KeyEventResult.handled;
    }

    if (ctrl && key == LogicalKeyboardKey.arrowLeft) {
      _seekToPrevSection();
      return KeyEventResult.handled;
    }
    if (ctrl && key == LogicalKeyboardKey.arrowRight) {
      _seekToNextSection();
      return KeyEventResult.handled;
    }

    if (key == LogicalKeyboardKey.arrowLeft) {
      _audio.seekRelative(const Duration(seconds: -5));
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.arrowRight) {
      _audio.seekRelative(const Duration(seconds: 5));
      return KeyEventResult.handled;
    }

    // Speed: [ and ]
    if (key == LogicalKeyboardKey.bracketLeft) {
      _setSpeed(_speed - 0.1);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.bracketRight) {
      _setSpeed(_speed + 0.1);
      return KeyEventResult.handled;
    }

    // Loop
    if (key == LogicalKeyboardKey.keyL) {
      _toggleLoop();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyA) {
      _setLoopStart();
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.keyB) {
      _setLoopEnd();
      return KeyEventResult.handled;
    }

    // Add section marker
    if (key == LogicalKeyboardKey.keyM) {
      _addSection();
      return KeyEventResult.handled;
    }

    // Cue point
    if (key == LogicalKeyboardKey.keyC) {
      _setCuePoint();
      return KeyEventResult.handled;
    }

    return KeyEventResult.ignored;
  }

  String _fmt(Duration d) {
    final m = d.inMinutes.toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    final ms = ((d.inMilliseconds % 1000) ~/ 10).toString().padLeft(2, '0');
    return '$m:$s.$ms';
  }

  @override
  void dispose() {
    for (final sub in _subs) {
      sub.cancel();
    }
    _save();
    _audio.dispose();
    _notesController.dispose();
    _sectionNotesController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return KeyboardListener(
      focusNode: _focusNode,
      onKeyEvent: (event) => _handleKey(_focusNode, event),
      child: Scaffold(
        backgroundColor: const Color(0xFF181825),
        appBar: AppBar(
          backgroundColor: const Color(0xFF1E1E2E),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back, color: Colors.white),
            onPressed: () {
              _save();
              Navigator.of(context).pop();
            },
          ),
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(_song.title,
                  style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.bold)),
              if (_song.artist != null)
                Text(_song.artist!,
                    style: const TextStyle(
                        color: Colors.white54, fontSize: 12)),
            ],
          ),
        ),
        body: Column(
          children: [
            // Seekbar
            _buildSeekbar(),
            // Controls row
            _buildControls(),
            // Speed control
            _buildSpeedControl(),
            // Loop controls
            _buildLoopControls(),
            const Divider(color: Color(0xFF313244), height: 1),
            // Bottom: sections + notes
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Sections panel
                  if (_showSections) _buildSectionsPanel(),
                  if (_showSections)
                    const VerticalDivider(
                        color: Color(0xFF313244), width: 1),
                  // Notes panel
                  _buildNotesPanel(),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSeekbar() {
    return GestureDetector(
      onHorizontalDragStart: (d) {
        _isDragging = true;
        _dragValue = d.localPosition.dx;
      },
      onHorizontalDragUpdate: (d) {
        setState(() => _dragValue = d.localPosition.dx);
      },
      onHorizontalDragEnd: (_) {
        final box = context.findRenderObject() as RenderBox?;
        final width = box?.size.width ?? MediaQuery.of(context).size.width;
        final fraction = (_dragValue / width).clamp(0.0, 1.0);
        final newPos = Duration(
            milliseconds: (fraction * _duration.inMilliseconds).round());
        _audio.seek(newPos);
        _isDragging = false;
      },
      onTapDown: (d) {
        final box = context.findRenderObject() as RenderBox?;
        final width = box?.size.width ?? MediaQuery.of(context).size.width;
        final fraction = (d.localPosition.dx / width).clamp(0.0, 1.0);
        final newPos = Duration(
            milliseconds: (fraction * _duration.inMilliseconds).round());
        _audio.seek(newPos);
        _focusNode.requestFocus();
      },
      child: Container(
        color: const Color(0xFF1E1E2E),
        padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
        child: Column(
          children: [
            SizedBox(
              height: 36,
              child: LayoutBuilder(builder: (ctx, constraints) {
                final pos = _isDragging
                    ? Duration(
                        milliseconds: ((_dragValue / constraints.maxWidth)
                                    .clamp(0.0, 1.0) *
                                _duration.inMilliseconds)
                            .round())
                    : _position;
                return CustomPaint(
                  size: Size(constraints.maxWidth, 36),
                  painter: SeekbarPainter(
                    position: pos,
                    duration: _duration,
                    loopStart: _loopStart,
                    loopEnd: _loopEnd,
                    loopEnabled: _loopEnabled,
                    sections: _song.sections,
                    cuePoint: _cuePoint,
                  ),
                );
              }),
            ),
            const SizedBox(height: 6),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(_fmt(_position),
                    style: const TextStyle(
                        color: Colors.white54,
                        fontSize: 12,
                        fontFamily: 'monospace')),
                if (_cuePoint != null)
                  GestureDetector(
                    onTap: _clearCuePoint,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.my_location,
                            size: 11, color: Color(0xFF94E2D5)),
                        const SizedBox(width: 3),
                        Text(
                          'cue: ${_fmt(_cuePoint!)}',
                          style: const TextStyle(
                              color: Color(0xFF94E2D5),
                              fontSize: 11,
                              fontFamily: 'monospace'),
                        ),
                        const SizedBox(width: 4),
                        const Icon(Icons.close,
                            size: 11, color: Color(0xFF94E2D5)),
                      ],
                    ),
                  ),
                Text(_fmt(_duration),
                    style: const TextStyle(
                        color: Colors.white24,
                        fontSize: 12,
                        fontFamily: 'monospace')),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildControls() {
    return Container(
      color: const Color(0xFF1E1E2E),
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          IconButton(
            icon: const Icon(Icons.skip_previous, color: Colors.white54),
            tooltip: 'Seção anterior (Ctrl+←)',
            onPressed: _seekToPrevSection,
          ),
          IconButton(
            icon: const Icon(Icons.replay_5, color: Colors.white70),
            tooltip: 'Recuar 5s (←)',
            onPressed: () => _audio.seekRelative(const Duration(seconds: -5)),
          ),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: () {
              _audio.togglePlay();
              _focusNode.requestFocus();
            },
            child: Container(
              width: 56,
              height: 56,
              decoration: const BoxDecoration(
                color: Color(0xFF89B4FA),
                shape: BoxShape.circle,
              ),
              child: Icon(
                _isPlaying ? Icons.pause : Icons.play_arrow,
                color: const Color(0xFF181825),
                size: 32,
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            icon: const Icon(Icons.forward_5, color: Colors.white70),
            tooltip: 'Avançar 5s (→)',
            onPressed: () => _audio.seekRelative(const Duration(seconds: 5)),
          ),
          IconButton(
            icon: const Icon(Icons.skip_next, color: Colors.white54),
            tooltip: 'Próxima seção (Ctrl+→)',
            onPressed: _seekToNextSection,
          ),
        ],
      ),
    );
  }

  Widget _buildSpeedControl() {
    return Container(
      color: const Color(0xFF1E1E2E),
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
      child: Row(
        children: [
          const Icon(Icons.speed, color: Colors.white38, size: 16),
          const SizedBox(width: 8),
          const Text('Velocidade',
              style: TextStyle(color: Colors.white38, fontSize: 12)),
          const SizedBox(width: 12),
          Expanded(
            child: SliderTheme(
              data: SliderThemeData(
                trackHeight: 3,
                thumbShape:
                    const RoundSliderThumbShape(enabledThumbRadius: 6),
                overlayShape:
                    const RoundSliderOverlayShape(overlayRadius: 12),
                activeTrackColor: const Color(0xFF89B4FA),
                inactiveTrackColor: const Color(0xFF45475A),
                thumbColor: Colors.white,
                overlayColor: const Color(0xFF89B4FA).withAlpha(50),
              ),
              child: Slider(
                value: _speed,
                min: 0.25,
                max: 2.0,
                divisions: 35,
                onChanged: _setSpeed,
              ),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            width: 40,
            child: Text(
              '${_speed.toStringAsFixed(2)}x',
              style: const TextStyle(
                  color: Color(0xFF89B4FA),
                  fontSize: 13,
                  fontFamily: 'monospace'),
              textAlign: TextAlign.right,
            ),
          ),
          const SizedBox(width: 8),
          TextButton(
            onPressed: () => _setSpeed(1.0),
            style: TextButton.styleFrom(
              padding:
                  const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              minimumSize: Size.zero,
            ),
            child: const Text('1x',
                style: TextStyle(color: Colors.white38, fontSize: 12)),
          ),
        ],
      ),
    );
  }

  Widget _buildLoopControls() {
    return Container(
      color: const Color(0xFF181825),
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Row(
        children: [
          _loopBtn(
            icon: Icons.fiber_manual_record,
            label: 'A',
            color: _loopStart != null
                ? const Color(0xFFFAB387)
                : Colors.white38,
            tooltip: 'Marcar início do loop (A)',
            onTap: _setLoopStart,
          ),
          const SizedBox(width: 8),
          if (_loopStart != null)
            Text(_fmt(_loopStart!),
                style: const TextStyle(
                    color: Color(0xFFFAB387),
                    fontSize: 11,
                    fontFamily: 'monospace')),
          const Spacer(),
          GestureDetector(
            onTap: _toggleLoop,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: _loopEnabled
                    ? const Color(0xFFFAB387).withAlpha(30)
                    : Colors.transparent,
                border: Border.all(
                  color: _loopEnabled
                      ? const Color(0xFFFAB387)
                      : Colors.white24,
                ),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.loop,
                      size: 16,
                      color: _loopEnabled
                          ? const Color(0xFFFAB387)
                          : Colors.white38),
                  const SizedBox(width: 4),
                  Text(
                    'Loop (L)',
                    style: TextStyle(
                      color: _loopEnabled
                          ? const Color(0xFFFAB387)
                          : Colors.white38,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
          ),
          const Spacer(),
          if (_loopEnd != null)
            Text(_fmt(_loopEnd!),
                style: const TextStyle(
                    color: Color(0xFFFAB387),
                    fontSize: 11,
                    fontFamily: 'monospace')),
          const SizedBox(width: 8),
          _loopBtn(
            icon: Icons.fiber_manual_record,
            label: 'B',
            color:
                _loopEnd != null ? const Color(0xFFFAB387) : Colors.white38,
            tooltip: 'Marcar fim do loop (B)',
            onTap: _setLoopEnd,
          ),
          const SizedBox(width: 8),
          GestureDetector(
            onTap: _clearLoop,
            child: const Icon(Icons.clear, color: Colors.white24, size: 18),
          ),
        ],
      ),
    );
  }

  Widget _loopBtn({
    required IconData icon,
    required String label,
    required Color color,
    required String tooltip,
    required VoidCallback onTap,
  }) {
    return Tooltip(
      message: tooltip,
      child: GestureDetector(
        onTap: onTap,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 10, color: color),
            const SizedBox(width: 2),
            Text(label,
                style: TextStyle(
                    color: color,
                    fontSize: 13,
                    fontWeight: FontWeight.bold)),
          ],
        ),
      ),
    );
  }

  Widget _buildSectionsPanel() {
    final sorted = [..._song.sections]
      ..sort((a, b) => a.startMs.compareTo(b.startMs));
    return SizedBox(
      width: 240,
      child: Column(
        children: [
          Container(
            color: const Color(0xFF1E1E2E),
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                const Text('Seções',
                    style: TextStyle(
                        color: Colors.white70,
                        fontWeight: FontWeight.bold,
                        fontSize: 13)),
                const Spacer(),
                Tooltip(
                  message: 'Adicionar seção no ponto atual (M)',
                  child: IconButton(
                    icon: const Icon(Icons.add, color: Color(0xFFA6E3A1)),
                    onPressed: _addSection,
                    iconSize: 18,
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton(
                  icon: const Icon(Icons.chevron_left, color: Colors.white38),
                  tooltip: 'Ocultar painel',
                  onPressed: () =>
                      setState(() => _showSections = false),
                  iconSize: 18,
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                ),
              ],
            ),
          ),
          const Divider(color: Color(0xFF313244), height: 1),
          Expanded(
            child: sorted.isEmpty
                ? const Center(
                    child: Text('Sem seções\nPressione M para adicionar',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                            color: Colors.white24, fontSize: 12)))
                : ListView.builder(
                    itemCount: sorted.length,
                    itemBuilder: (ctx, i) {
                      final section = sorted[i];
                      final selected = _selectedSection?.id == section.id;
                      return GestureDetector(
                        onTap: () => _seekToSection(section),
                        child: Container(
                          color: selected
                              ? const Color(0xFF313244)
                              : Colors.transparent,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 8),
                          child: Row(
                            children: [
                              Container(
                                width: 4,
                                height: 36,
                                decoration: BoxDecoration(
                                  color: Color(section.colorValue),
                                  borderRadius: BorderRadius.circular(2),
                                ),
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      section.name,
                                      style: TextStyle(
                                        color: selected
                                            ? Colors.white
                                            : Colors.white70,
                                        fontSize: 13,
                                        fontWeight: selected
                                            ? FontWeight.bold
                                            : FontWeight.normal,
                                      ),
                                    ),
                                    Text(
                                      _fmt(Duration(
                                          milliseconds: section.startMs)),
                                      style: const TextStyle(
                                          color: Colors.white38,
                                          fontSize: 11,
                                          fontFamily: 'monospace'),
                                    ),
                                  ],
                                ),
                              ),
                              PopupMenuButton<String>(
                                color: const Color(0xFF313244),
                                icon: const Icon(Icons.more_vert,
                                    color: Colors.white24, size: 16),
                                onSelected: (v) {
                                  if (v == 'rename') {
                                    _renameSection(section);
                                  } else if (v == 'setstart') {
                                    setState(() => section.startMs =
                                        _position.inMilliseconds);
                                    _save();
                                  } else if (v == 'delete') {
                                    _deleteSection(section);
                                  }
                                },
                                itemBuilder: (_) => [
                                  const PopupMenuItem(
                                    value: 'rename',
                                    child: Text('Renomear',
                                        style: TextStyle(
                                            color: Colors.white70)),
                                  ),
                                  const PopupMenuItem(
                                    value: 'setstart',
                                    child: Text('Mover para posição atual',
                                        style: TextStyle(
                                            color: Colors.white70)),
                                  ),
                                  const PopupMenuItem(
                                    value: 'delete',
                                    child: Text('Excluir',
                                        style: TextStyle(
                                            color: Color(0xFFF38BA8))),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
          ),
          // Section notes
          if (_selectedSection != null)
            Column(
              children: [
                const Divider(color: Color(0xFF313244), height: 1),
                Container(
                  color: const Color(0xFF1E1E2E),
                  padding: const EdgeInsets.all(8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Notas: ${_selectedSection!.name}',
                        style: const TextStyle(
                            color: Colors.white54, fontSize: 11),
                      ),
                      const SizedBox(height: 4),
                      TextField(
                        controller: _sectionNotesController,
                        maxLines: 3,
                        style: const TextStyle(
                            color: Colors.white, fontSize: 12),
                        decoration: const InputDecoration(
                          border: OutlineInputBorder(
                            borderSide:
                                BorderSide(color: Color(0xFF45475A)),
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderSide:
                                BorderSide(color: Color(0xFF45475A)),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderSide:
                                BorderSide(color: Color(0xFF89B4FA)),
                          ),
                          contentPadding: EdgeInsets.all(8),
                          hintText: 'Notas da seção...',
                          hintStyle: TextStyle(color: Colors.white24),
                        ),
                        onChanged: (v) {
                          _selectedSection!.notes = v;
                          _save();
                        },
                      ),
                    ],
                  ),
                ),
              ],
            ),
        ],
      ),
    );
  }

  Widget _buildNotesPanel() {
    return Expanded(
      child: Column(
        children: [
          Container(
            color: const Color(0xFF1E1E2E),
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                const Text('Notas da música',
                    style: TextStyle(
                        color: Colors.white70,
                        fontWeight: FontWeight.bold,
                        fontSize: 13)),
                const Spacer(),
                if (!_showSections)
                  IconButton(
                    icon: const Icon(Icons.chevron_right,
                        color: Colors.white38),
                    tooltip: 'Mostrar seções',
                    onPressed: () =>
                        setState(() => _showSections = true),
                    iconSize: 18,
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                  ),
              ],
            ),
          ),
          const Divider(color: Color(0xFF313244), height: 1),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: TextField(
                controller: _notesController,
                maxLines: null,
                expands: true,
                textAlignVertical: TextAlignVertical.top,
                style: const TextStyle(
                    color: Colors.white, fontSize: 13, height: 1.5),
                decoration: const InputDecoration(
                  border: InputBorder.none,
                  hintText:
                      'Escreva notas, acordes, letras...\n\nAtalhos:\n  Espaço: Play/Pause\n  ←/→: ±5 segundos\n  Ctrl+←/→: Seção anterior/próxima\n  [/]: Velocidade -0.1/+0.1\n  A/B: Marcar início/fim do loop\n  L: Ativar/desativar loop\n  M: Adicionar seção no ponto atual\n  C: Definir cue point (início do playback)',
                  hintStyle: TextStyle(color: Colors.white12),
                ),
                onChanged: (_) => _save(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
