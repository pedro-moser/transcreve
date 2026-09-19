import 'package:hive/hive.dart';
import 'section.dart';

part 'song.g.dart';

@HiveType(typeId: 0)
class Song extends HiveObject {
  @HiveField(0)
  String id;

  @HiveField(1)
  String title;

  @HiveField(2)
  String? artist;

  @HiveField(3)
  String filePath;

  @HiveField(4)
  String? youtubeUrl;

  @HiveField(5)
  List<Section> sections;

  @HiveField(6)
  String notes;

  @HiveField(7)
  int durationMs;

  @HiveField(8)
  DateTime addedAt;

  Song({
    required this.id,
    required this.title,
    this.artist,
    required this.filePath,
    this.youtubeUrl,
    List<Section>? sections,
    this.notes = '',
    this.durationMs = 0,
    DateTime? addedAt,
  })  : sections = sections ?? [],
        addedAt = addedAt ?? DateTime.now();
}
