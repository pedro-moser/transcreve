import 'package:hive/hive.dart';

part 'section.g.dart';

@HiveType(typeId: 1)
class Section extends HiveObject {
  @HiveField(0)
  String id;

  @HiveField(1)
  String name;

  @HiveField(2)
  int startMs;

  @HiveField(3)
  int? endMs;

  @HiveField(4)
  int colorValue;

  @HiveField(5)
  String notes;

  Section({
    required this.id,
    required this.name,
    required this.startMs,
    this.endMs,
    this.colorValue = 0xFF4CAF50,
    this.notes = '',
  });
}
