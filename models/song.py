from dataclasses import dataclass, field
from datetime import datetime
import uuid

from .section import Section


@dataclass
class Song:
    title: str
    file_path: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    artist: str | None = None
    youtube_url: str | None = None
    sections: list[Section] = field(default_factory=list)
    notes: str = ""
    duration_ms: int = 0
    added_at: datetime = field(default_factory=datetime.now)
