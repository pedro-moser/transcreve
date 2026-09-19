from dataclasses import dataclass, field
import uuid


@dataclass
class Section:
    name: str
    start_ms: int
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    end_ms: int | None = None
    color_hex: str = "#A6E3A1"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "color_hex": self.color_hex,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Section":
        return cls(
            id=d["id"],
            name=d["name"],
            start_ms=d["start_ms"],
            end_ms=d.get("end_ms"),
            color_hex=d.get("color_hex", "#A6E3A1"),
            notes=d.get("notes", ""),
        )
