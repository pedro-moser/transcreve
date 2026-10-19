"""Tunings offered for the tab, by instrument and number of strings.

The first tuning of each string count is the one picked when the user
switches to that count. Tunings are tuples of open pitches from string 1,
the highest, as in services.fretting.
"""

from typing import NamedTuple

from services.chord_service import NOTE_NAMES

GUITAR = "guitar"
BASS = "bass"


class Tuning(NamedTuple):
    name: str
    strings: tuple[int, ...]


def _pitch(name: str) -> int:
    """MIDI pitch of a note name with octave, such as "F#1" or "Eb4"."""
    letter, octave = name[:-1], int(name[-1])
    if letter.endswith("b"):
        index = NOTE_NAMES.index(letter[0]) - 1
    else:
        index = NOTE_NAMES.index(letter)
    return 12 * (octave + 1) + index


def _tuning(name: str, low_to_high: str) -> Tuning:
    return Tuning(name, tuple(_pitch(n) for n in reversed(low_to_high.split())))


TUNINGS: dict[str, dict[int, list[Tuning]]] = {
    GUITAR: {
        6: [
            _tuning("E padrão", "E2 A2 D3 G3 B3 E4"),
            _tuning("Eb padrão", "Eb2 Ab2 Db3 Gb3 Bb3 Eb4"),
            _tuning("Drop D", "D2 A2 D3 G3 B3 E4"),
            _tuning("D padrão", "D2 G2 C3 F3 A3 D4"),
            _tuning("Drop C", "C2 G2 C3 F3 A3 D4"),
            _tuning("C padrão", "C2 F2 Bb2 Eb3 G3 C4"),
            _tuning("Drop B", "B1 F#2 B2 E3 G#3 C#4"),
            _tuning("DADGAD", "D2 A2 D3 G3 A3 D4"),
            _tuning("Open G", "D2 G2 D3 G3 B3 D4"),
        ],
        7: [
            _tuning("B padrão", "B1 E2 A2 D3 G3 B3 E4"),
            _tuning("Drop A", "A1 E2 A2 D3 G3 B3 E4"),
            _tuning("A padrão", "A1 D2 G2 C3 F3 A3 D4"),
        ],
        8: [
            _tuning("F# padrão", "F#1 B1 E2 A2 D3 G3 B3 E4"),
            _tuning("F padrão", "F1 Bb1 Eb2 Ab2 Db3 Gb3 Bb3 Eb4"),
            _tuning("Drop E", "E1 B1 E2 A2 D3 G3 B3 E4"),
        ],
    },
    BASS: {
        4: [
            _tuning("E padrão", "E1 A1 D2 G2"),
            _tuning("Eb padrão", "Eb1 Ab1 Db2 Gb2"),
            _tuning("Drop D", "D1 A1 D2 G2"),
            _tuning("D padrão", "D1 G1 C2 F2"),
            _tuning("Drop C", "C1 G1 C2 F2"),
        ],
        5: [
            _tuning("B padrão", "B0 E1 A1 D2 G2"),
            _tuning("Drop A", "A0 E1 A1 D2 G2"),
        ],
        6: [
            _tuning("B padrão", "B0 E1 A1 D2 G2 C3"),
        ],
    },
}


def default(instrument: str) -> tuple[int, ...]:
    """Standard tuning of the instrument's usual string count."""
    usual = 6 if instrument == GUITAR else 4
    return TUNINGS[instrument][usual][0].strings


def name(instrument: str, strings: tuple[int, ...]) -> str:
    """Preset name of ``strings``, or its notes from the low string up."""
    for tuning in TUNINGS[instrument].get(len(strings), []):
        if tuning.strings == strings:
            return tuning.name
    return " ".join(NOTE_NAMES[p % 12] for p in reversed(strings))
