from typing import NamedTuple


class PositionFix(NamedTuple):
    """A string the user chose for one detected note.

    Anchored on (pitch, onset) rather than on a note id, so it follows the
    note across re-analysis (SPEC-notas.md, modelo de dados).
    """

    pitch: int  # MIDI, sounding
    onset: float  # seconds, onset of the note when it was fixed
    string: int  # 1 = the highest string, as in tab
