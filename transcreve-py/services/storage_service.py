import json
import sqlite3
from datetime import datetime
from pathlib import Path

from models.section import Section
from models.song import Song


class StorageService:
    _db_path: Path
    _conn: sqlite3.Connection

    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            data_dir = Path.home() / ".local" / "share" / "transcreve"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "transcreve.db"
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS songs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT,
                file_path TEXT NOT NULL,
                youtube_url TEXT,
                sections TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                added_at TEXT NOT NULL
            );
        """)
        self._conn.commit()

    def get_songs(self) -> list[Song]:
        rows = self._conn.execute(
            "SELECT * FROM songs ORDER BY added_at DESC"
        ).fetchall()
        return [self._row_to_song(row) for row in rows]

    def get_song(self, song_id: str) -> Song | None:
        row = self._conn.execute(
            "SELECT * FROM songs WHERE id = ?", (song_id,)
        ).fetchone()
        return self._row_to_song(row) if row else None

    def save_song(self, song: Song):
        sections_json = json.dumps([s.to_dict() for s in song.sections])
        self._conn.execute(
            """INSERT OR REPLACE INTO songs
               (id, title, artist, file_path, youtube_url, sections, notes, duration_ms, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                song.id,
                song.title,
                song.artist,
                song.file_path,
                song.youtube_url,
                sections_json,
                song.notes,
                song.duration_ms,
                song.added_at.isoformat(),
            ),
        )
        self._conn.commit()

    def delete_song(self, song_id: str):
        self._conn.execute("DELETE FROM songs WHERE id = ?", (song_id,))
        self._conn.commit()

    def _row_to_song(self, row: sqlite3.Row) -> Song:
        sections_data = json.loads(row["sections"])
        sections = [Section.from_dict(s) for s in sections_data]
        return Song(
            id=row["id"],
            title=row["title"],
            artist=row["artist"],
            file_path=row["file_path"],
            youtube_url=row["youtube_url"],
            sections=sections,
            notes=row["notes"],
            duration_ms=row["duration_ms"],
            added_at=datetime.fromisoformat(row["added_at"]),
        )

    def close(self):
        self._conn.close()
