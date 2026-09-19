import 'dart:io';
import 'package:path_provider/path_provider.dart';

class YoutubeService {
  static Future<({String filePath, String title, String? artist})> download(
    String url, {
    void Function(String)? onProgress,
  }) async {
    final dir = await getApplicationSupportDirectory();
    final musicDir = Directory('${dir.path}/music');
    await musicDir.create(recursive: true);

    // Get metadata first
    final metaResult = await Process.run('yt-dlp', [
      '--print',
      '%(title)s\n%(uploader)s',
      '--no-playlist',
      url,
    ]);

    String title = 'Unknown';
    String? artist;
    if (metaResult.exitCode == 0) {
      final lines = (metaResult.stdout as String).trim().split('\n');
      if (lines.isNotEmpty) title = lines[0].trim();
      if (lines.length > 1) artist = lines[1].trim();
    }

    // Sanitize title for filename
    final safeTitle = title.replaceAll(RegExp(r'[<>:"/\\|?*]'), '_');
    final outputPath = '${musicDir.path}/$safeTitle.%(ext)s';

    onProgress?.call('Baixando "$title"...');

    final process = await Process.start('yt-dlp', [
      '-x',
      '--audio-format',
      'mp3',
      '--audio-quality',
      '0',
      '--no-playlist',
      '-o',
      outputPath,
      url,
    ]);

    process.stdout.transform(const SystemEncoding().decoder).listen((data) {
      onProgress?.call(data.trim());
    });

    final exitCode = await process.exitCode;
    if (exitCode != 0) {
      final err = await process.stderr.transform(const SystemEncoding().decoder).join();
      throw Exception('yt-dlp falhou (código $exitCode): $err');
    }

    // Find the downloaded file
    final files = musicDir
        .listSync()
        .whereType<File>()
        .where((f) => f.path.contains(safeTitle))
        .toList();

    if (files.isEmpty) {
      throw Exception('Arquivo não encontrado após download');
    }

    files.sort((a, b) =>
        b.statSync().modified.compareTo(a.statSync().modified));

    return (filePath: files.first.path, title: title, artist: artist);
  }
}
