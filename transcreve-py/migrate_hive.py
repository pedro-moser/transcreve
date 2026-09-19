"""Migrate songs from Flutter Hive database to Python SQLite database.

Hive uses a binary format. This script parses the songs.hive file
and imports entries into the new SQLite database.
"""
import struct
import sys
from datetime import datetime
from pathlib import Path

import soundfile as sf

from models.section import Section
from models.song import Song
from services.storage_service import StorageService

HIVE_PATH = Path.home() / "Documents" / "songs.hive"


def read_hive_string(data: bytes, offset: int) -> tuple[str, int]:
    """Read a length-prefixed string from Hive binary data."""
    if offset + 4 > len(data):
        return "", offset
    length = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    s = data[offset : offset + length].decode("utf-8", errors="replace")
    return s, offset + length


def read_hive_byte(data: bytes, offset: int) -> tuple[int, int]:
    return data[offset], offset + 1


def parse_songs(data: bytes) -> list[dict]:
    """Parse songs from Hive binary, extracting text fields heuristically."""
    songs = []
    # find all UUID-like patterns as song boundaries
    import re

    text = data.decode("latin-1")
    uuids = list(re.finditer(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text))

    # group unique UUIDs
    seen = {}
    for m in uuids:
        uid = m.group()
        if uid not in seen:
            seen[uid] = m.start()

    # for each unique UUID, extract fields that follow it
    for uid, start in seen.items():
        # scan forward from the UUID for string fields
        # Hive stores fields by index: 0=id, 1=title, 2=artist, 3=filePath, 4=youtubeUrl
        # Each field is prefixed with field_index byte + type byte + length
        song_data = {"id": uid}

        # find the structured data block after the UUID
        # look for the pattern: field_index(1b) type(1b=04 for string) length(4b) data
        pos = start + 36  # skip past UUID
        fields_found = 0
        field_names = {1: "title", 2: "artist", 3: "file_path", 4: "youtube_url"}

        while pos < len(data) - 5 and fields_found < 10:
            field_idx = data[pos]
            field_type = data[pos + 1] if pos + 1 < len(data) else 0

            if field_idx in field_names and field_type == 0x04:
                # string field
                length = struct.unpack_from("<I", data, pos + 2)[0]
                if 0 < length < 500:
                    value = data[pos + 6 : pos + 6 + length].decode("utf-8", errors="replace")
                    song_data[field_names[field_idx]] = value
                    pos = pos + 6 + length
                    fields_found += 1
                    continue

            pos += 1

        if "title" in song_data and "file_path" in song_data:
            songs.append(song_data)

    # deduplicate by title+file_path (Hive stores multiple revisions)
    unique = {}
    for s in songs:
        key = (s.get("title", ""), s.get("file_path", ""))
        if key not in unique:
            unique[key] = s
    return list(unique.values())


def migrate():
    if not HIVE_PATH.exists():
        print(f"Hive database not found at {HIVE_PATH}")
        print("Nothing to migrate.")
        return

    data = HIVE_PATH.read_bytes()
    print(f"Read {len(data)} bytes from {HIVE_PATH}")

    songs_data = parse_songs(data)
    print(f"Found {len(songs_data)} song(s) in Hive database")

    if not songs_data:
        print("No songs to migrate.")
        return

    storage = StorageService()
    existing = {s.id for s in storage.get_songs()}

    imported = 0
    for sd in songs_data:
        if sd["id"] in existing:
            print(f"  Skipping '{sd.get('title', '?')}' (already exists)")
            continue

        file_path = sd.get("file_path", "")
        duration_ms = 0
        if Path(file_path).exists():
            try:
                info = sf.info(file_path)
                duration_ms = int(info.duration * 1000)
            except Exception:
                pass

        song = Song(
            id=sd["id"],
            title=sd.get("title", "Unknown"),
            file_path=file_path,
            artist=sd.get("artist"),
            youtube_url=sd.get("youtube_url"),
            duration_ms=duration_ms,
            added_at=datetime.now(),
        )
        storage.save_song(song)
        imported += 1
        exists = "✓" if Path(file_path).exists() else "✗ (file missing)"
        print(f"  Imported: {song.title} — {song.artist or 'N/A'} {exists}")

    storage.close()
    print(f"\nMigration complete: {imported} song(s) imported.")


if __name__ == "__main__":
    migrate()
