import 'package:hive_flutter/hive_flutter.dart';
import '../models/song.dart';
import '../models/section.dart';

class StorageService {
  static const _songsBoxName = 'songs';
  static late Box<Song> _songsBox;

  static Future<void> init() async {
    await Hive.initFlutter();
    Hive.registerAdapter(SongAdapter());
    Hive.registerAdapter(SectionAdapter());
    _songsBox = await Hive.openBox<Song>(_songsBoxName);
  }

  static List<Song> getSongs() {
    return _songsBox.values.toList()
      ..sort((a, b) => b.addedAt.compareTo(a.addedAt));
  }

  static Future<void> saveSong(Song song) async {
    await _songsBox.put(song.id, song);
  }

  static Future<void> deleteSong(String id) async {
    await _songsBox.delete(id);
  }

  static Song? getSong(String id) {
    return _songsBox.get(id);
  }
}
