import 'dart:io';
import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';
import 'package:file_picker/file_picker.dart';
import '../models/song.dart';
import '../services/storage_service.dart';
import '../services/youtube_service.dart';
import '../services/audio_service.dart';
import 'player_screen.dart';

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  List<Song> _songs = [];
  bool _loading = false;
  String _status = '';

  @override
  void initState() {
    super.initState();
    _loadSongs();
  }

  void _loadSongs() {
    setState(() => _songs = StorageService.getSongs());
  }

  Future<void> _addYoutubeUrl() async {
    final urlController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E2E),
        title: const Text('Adicionar do YouTube',
            style: TextStyle(color: Colors.white)),
        content: TextField(
          controller: urlController,
          autofocus: true,
          style: const TextStyle(color: Colors.white),
          decoration: const InputDecoration(
            hintText: 'Cole a URL do YouTube aqui',
            hintStyle: TextStyle(color: Colors.white38),
            enabledBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: Colors.white24)),
            focusedBorder: UnderlineInputBorder(
                borderSide: BorderSide(color: Color(0xFF89B4FA))),
          ),
          onSubmitted: (_) => Navigator.of(ctx).pop(true),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancelar',
                style: TextStyle(color: Colors.white54)),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Baixar',
                style: TextStyle(color: Color(0xFF89B4FA))),
          ),
        ],
      ),
    );

    if (confirmed != true || urlController.text.trim().isEmpty) return;

    setState(() {
      _loading = true;
      _status = 'Iniciando download...';
    });

    try {
      final result = await YoutubeService.download(
        urlController.text.trim(),
        onProgress: (msg) => setState(() => _status = msg),
      );

      final audioSvc = AudioService();
      final durationMs = await audioSvc.getDurationMs(result.filePath);
      await audioSvc.dispose();

      final song = Song(
        id: const Uuid().v4(),
        title: result.title,
        artist: result.artist,
        filePath: result.filePath,
        youtubeUrl: urlController.text.trim(),
        durationMs: durationMs,
      );

      await StorageService.saveSong(song);
      _loadSongs();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Erro: $e'),
            backgroundColor: const Color(0xFFF38BA8),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _addLocalFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.audio,
      allowMultiple: false,
    );

    if (result == null || result.files.isEmpty) return;

    final file = result.files.first;
    if (file.path == null) return;

    setState(() {
      _loading = true;
      _status = 'Processando arquivo...';
    });

    try {
      final audioSvc = AudioService();
      final durationMs = await audioSvc.getDurationMs(file.path!);
      await audioSvc.dispose();

      final nameWithoutExt = file.name.replaceAll(RegExp(r'\.[^.]+$'), '');
      final song = Song(
        id: const Uuid().v4(),
        title: nameWithoutExt,
        filePath: file.path!,
        durationMs: durationMs,
      );

      await StorageService.saveSong(song);
      _loadSongs();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Erro: $e'),
              backgroundColor: const Color(0xFFF38BA8)),
        );
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _deleteSong(Song song) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E1E2E),
        title: const Text('Remover música',
            style: TextStyle(color: Colors.white)),
        content: Text('Remover "${song.title}" da biblioteca?',
            style: const TextStyle(color: Colors.white70)),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancelar',
                style: TextStyle(color: Colors.white54)),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Remover',
                style: TextStyle(color: Color(0xFFF38BA8))),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await StorageService.deleteSong(song.id);
    _loadSongs();
  }

  String _formatDuration(int ms) {
    final d = Duration(milliseconds: ms);
    final m = d.inMinutes.toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF181825),
      appBar: AppBar(
        backgroundColor: const Color(0xFF1E1E2E),
        title: const Text('Transcreve',
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(
            icon: const Icon(Icons.folder_open, color: Color(0xFFA6E3A1)),
            tooltip: 'Adicionar arquivo local',
            onPressed: _loading ? null : _addLocalFile,
          ),
          IconButton(
            icon: const Icon(Icons.add_link, color: Color(0xFF89B4FA)),
            tooltip: 'Adicionar URL do YouTube',
            onPressed: _loading ? null : _addYoutubeUrl,
          ),
        ],
      ),
      body: Column(
        children: [
          if (_loading)
            Container(
              color: const Color(0xFF313244),
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Color(0xFF89B4FA),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      _status,
                      style: const TextStyle(color: Colors.white70, fontSize: 12),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ],
              ),
            ),
          Expanded(
            child: _songs.isEmpty
                ? Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        const Icon(Icons.music_note,
                            size: 64, color: Colors.white24),
                        const SizedBox(height: 16),
                        const Text('Biblioteca vazia',
                            style: TextStyle(
                                color: Colors.white38, fontSize: 18)),
                        const SizedBox(height: 8),
                        const Text(
                            'Adicione músicas via URL do YouTube ou arquivo local',
                            style: TextStyle(
                                color: Colors.white24, fontSize: 13)),
                      ],
                    ),
                  )
                : ListView.builder(
                    itemCount: _songs.length,
                    itemBuilder: (ctx, i) {
                      final song = _songs[i];
                      final exists = File(song.filePath).existsSync();
                      return ListTile(
                        tileColor: i.isEven
                            ? const Color(0xFF1E1E2E)
                            : const Color(0xFF181825),
                        leading: CircleAvatar(
                          backgroundColor: exists
                              ? const Color(0xFF313244)
                              : const Color(0xFF45475A),
                          child: Icon(
                            exists ? Icons.music_note : Icons.broken_image,
                            color: exists
                                ? const Color(0xFF89B4FA)
                                : Colors.white24,
                            size: 20,
                          ),
                        ),
                        title: Text(
                          song.title,
                          style: TextStyle(
                            color: exists ? Colors.white : Colors.white38,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                        subtitle: Text(
                          [
                            if (song.artist != null) song.artist!,
                            if (song.durationMs > 0)
                              _formatDuration(song.durationMs),
                            if (song.sections.isNotEmpty)
                              '${song.sections.length} seções',
                          ].join(' · '),
                          style: const TextStyle(
                              color: Colors.white38, fontSize: 12),
                        ),
                        trailing: IconButton(
                          icon: const Icon(Icons.delete_outline,
                              color: Colors.white24),
                          onPressed: () => _deleteSong(song),
                        ),
                        onTap: exists
                            ? () async {
                                await Navigator.of(context).push(
                                  MaterialPageRoute(
                                    builder: (_) => PlayerScreen(song: song),
                                  ),
                                );
                                _loadSongs();
                              }
                            : null,
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
