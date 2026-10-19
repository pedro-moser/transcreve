"""String and fret for each detected note, for the tab view.

Notes that start together form an event, usually a strum. Each event gets
the fingerings that a hand can play, and a Viterbi pass picks the sequence
that keeps the hand still: moving the hand out of the frets it already covers
costs, open strings cost a little, and there is no pull toward the first
frets (SPEC-notas.md, decisão 5).
Positions the user fixed are hard constraints.
"""

from typing import NamedTuple, Sequence

import numpy as np

from models.position_fix import PositionFix
from services.chord_service import NOTE_NAMES

STANDARD_TUNING = (64, 59, 55, 50, 45, 40)  # open strings, 1 (high e) to 6
MAX_FRET = 20
MAX_SPAN = 4  # frets between the lowest and highest fretted note of a chord
EVENT_WINDOW = 0.05  # s; a note starting this soon after another joins its strum
MAX_EVENT_LENGTH = 0.12  # s; a strum never spans more than this
ANCHOR_TOLERANCE = 0.05  # s; how far a fixed position may drift on re-analysis
MAX_FINGERINGS = 60  # per event, cheapest first

# The hand sits at a position: the index finger at fret h covers frets h to
# h + MAX_SPAN. Moving between positions is what "mão parada" avoids.
# Costs are in frets of hand movement.
MOVE_COST = 1.0  # per fret the hand position shifts
REST_GAP = 1.0  # s; after this long, the hand has time to move
REST_MOVE_FACTOR = 0.3
OPEN_STRING_COST = 2.0  # per open string: fine when no fret is close by
SPAN_COST = 0.3  # per fret of stretch inside a chord
CUT_COST = 3.0  # re-plucking a string that is still sounding another note
HEIGHT_COST = 0.02  # per fret of hand position; only breaks ties
# Above this fret, staying costs: otherwise one high harmonic (an A5 only fits
# the e string at 17) lifts the hand and "mão parada" keeps it up there.
HIGH_FRET = 12
HIGH_FRET_COST = 0.5  # per fret above HIGH_FRET, for the highest fretted note
# A chord may leave one note out of its shape, at this cost times the note's
# score: a faint harmonic should not bend the whole chord into a far position.
LEAVE_OUT_COST = 10.0


class Position(NamedTuple):
    string: int  # 1 = high e
    fret: int


class TabNote(NamedTuple):
    onset: float  # seconds
    offset: float
    pitch: int
    score: float
    string: int | None  # None when the pitch is out of the guitar's range
    fret: int | None
    playable: bool  # False when the note does not fit its event's fingering
    fixed: bool  # string chosen by the user


def positions(pitch: int, tuning: Sequence[int] = STANDARD_TUNING) -> list[Position]:
    """Every place ``pitch`` can be played, from the high string down."""
    return [
        Position(string, pitch - open_pitch)
        for string, open_pitch in enumerate(tuning, start=1)
        if 0 <= pitch - open_pitch <= MAX_FRET
    ]


def _matching_fix(note, fixes: Sequence[PositionFix]) -> PositionFix | None:
    candidates = [
        fix for fix in fixes
        if fix.pitch == note.pitch and abs(fix.onset - note.onset) <= ANCHOR_TOLERANCE
    ]
    return min(candidates, key=lambda fix: abs(fix.onset - note.onset), default=None)


def orphan_fixes(notes, fixes: Sequence[PositionFix],
                 tuning: Sequence[int] = STANDARD_TUNING) -> list[PositionFix]:
    """Fixes that no note matches, or whose string cannot play the pitch."""
    orphans = []
    for fix in fixes:
        playable = any(p.string == fix.string for p in positions(fix.pitch, tuning))
        anchored = any(
            n.pitch == fix.pitch and abs(n.onset - fix.onset) <= ANCHOR_TOLERANCE
            for n in notes
        )
        if not (playable and anchored):
            orphans.append(fix)
    return orphans


def group_events(notes) -> list[list]:
    """Notes sorted by onset and split into strums.

    The same pitch twice in one strum is a detection artifact, usually a short
    onset fragment, so it becomes one note spanning both.
    """
    events: list[list] = []
    for note in sorted(notes, key=lambda n: (n.onset, n.pitch)):
        if (
            events
            and note.onset - events[-1][-1].onset <= EVENT_WINDOW
            and note.onset - events[-1][0].onset <= MAX_EVENT_LENGTH
        ):
            events[-1].append(note)
        else:
            events.append([note])
    return [_merge_unisons(event) for event in events]


def _merge_unisons(event: list) -> list:
    by_pitch = {}
    for note in event:
        kept = by_pitch.get(note.pitch)
        by_pitch[note.pitch] = note if kept is None else kept._replace(
            offset=max(kept.offset, note.offset), score=max(kept.score, note.score)
        )
    return sorted(by_pitch.values(), key=lambda n: (n.onset, n.pitch))


class _Fingering(NamedTuple):
    notes: tuple  # indices into _Event.all_notes of the notes it places
    frets: tuple  # aligned with notes
    strings: tuple
    low: int  # lowest and highest fretted note; 0 when every string is open
    high: int
    cost: float  # cost of the shape itself


class _Event:
    def __init__(self, notes, fixes, tuning):
        self.onset = min(n.onset for n in notes)
        fixed = {}
        for i, note in enumerate(notes):
            fix = _matching_fix(note, fixes)
            if fix is not None and any(p.string == fix.string for p in positions(note.pitch, tuning)):
                fixed[i] = fix.string
        self.all_notes = notes
        self.fixed = fixed
        # Out-of-range notes never enter the search; at most six notes do.
        playable = [i for i, n in enumerate(notes) if positions(n.pitch, tuning)]
        playable.sort(key=lambda i: (i not in fixed, -notes[i].score))
        self.dropped = set(playable[6:])
        self.members = playable[:6]
        self.tuning = tuning
        self.fingerings = self._search()
        self._states()

    def _states(self):
        """One Viterbi state per fingering and hand position that reaches it.

        Open strings do not constrain the hand, so a fingering without fretted
        notes keeps whatever position the hand had.
        """
        fingering, hand = [], []
        for k, f in enumerate(self.fingerings):
            if f.high == 0:
                hands = range(1, MAX_FRET + 1)
            else:
                hands = range(max(1, f.high - MAX_SPAN), f.low + 1)
            for h in hands:
                fingering.append(k)
                hand.append(h)
        self.state_fingering = np.array(fingering)
        self.state_hand = np.array(hand, dtype=float)
        shape = np.array([f.cost for f in self.fingerings])
        self.state_cost = shape[self.state_fingering] + HEIGHT_COST * self.state_hand

    def _search(self) -> list[_Fingering]:
        """Playable fingerings; drops the weakest note until one exists."""
        while True:
            found = self._enumerate(self.members)
            if len(self.members) > 1:
                for i in self.members:
                    if i in self.fixed:
                        continue
                    rest = [j for j in self.members if j != i]
                    penalty = LEAVE_OUT_COST * self.all_notes[i].score
                    found += [f._replace(cost=f.cost + penalty) for f in self._enumerate(rest)]
            if found or not self.members:
                found.sort(key=lambda f: f.cost)
                return found[:MAX_FINGERINGS]
            # The weakest note goes first; a fixed note only when nothing
            # else is left, so the user's choices win.
            weakest = min(
                self.members,
                key=lambda i: (i in self.fixed, self.all_notes[i].score),
            )
            self.members.remove(weakest)
            self.dropped.add(weakest)

    def _enumerate(self, members: list[int]) -> list[_Fingering]:
        # The user's fixes may need a stretch the limit would forbid.
        span_limit = not self.fixed
        options = []
        for i in members:
            choices = positions(self.all_notes[i].pitch, self.tuning)
            if i in self.fixed:
                choices = [p for p in choices if p.string == self.fixed[i]]
            options.append(choices)
        order = sorted(range(len(options)), key=lambda k: len(options[k]))
        results = []

        def walk(k, used, chosen):
            if k == len(order):
                frets = [chosen[j].fret for j in range(len(options))]
                fretted = [f for f in frets if f > 0]
                low, high = (min(fretted), max(fretted)) if fretted else (0, 0)
                if span_limit and high - low > MAX_SPAN:
                    return
                cost = (
                    OPEN_STRING_COST * (len(frets) - len(fretted))
                    + SPAN_COST * (high - low)
                    + HIGH_FRET_COST * max(0, high - HIGH_FRET)
                )
                results.append(_Fingering(
                    tuple(members), tuple(frets),
                    tuple(chosen[j].string for j in range(len(options))), low, high, cost,
                ))
                return
            j = order[k]
            for p in options[j]:
                if p.string in used:
                    continue
                chosen[j] = p
                walk(k + 1, used | {p.string}, chosen)
            chosen.pop(j, None)

        walk(0, frozenset(), {})
        return results


def _ringing(event: _Event, fingering: _Fingering, at: float) -> np.ndarray:
    """Pitch still sounding on each string at time ``at``, or -1."""
    ringing = np.full(6, -1)
    for i, string in zip(fingering.notes, fingering.strings):
        if event.all_notes[i].offset > at + EVENT_WINDOW:
            ringing[string - 1] = event.all_notes[i].pitch
    return ringing


def _played(event: _Event, fingering: _Fingering) -> np.ndarray:
    played = np.full(6, -1)
    for i, string in zip(fingering.notes, fingering.strings):
        played[string - 1] = event.all_notes[i].pitch
    return played


def _transition(prev: _Event, cur: _Event) -> np.ndarray:
    """Cost from each state of ``prev`` to each state of ``cur``."""
    move = np.abs(prev.state_hand[:, None] - cur.state_hand[None, :])
    if cur.onset - prev.onset > REST_GAP:
        move *= REST_MOVE_FACTOR
    ringing = np.array([_ringing(prev, f, cur.onset) for f in prev.fingerings])
    played = np.array([_played(cur, f) for f in cur.fingerings])
    cut = (
        (ringing[:, None, :] >= 0)
        & (played[None, :, :] >= 0)
        & (ringing[:, None, :] != played[None, :, :])
    ).sum(axis=2)
    cut = cut[prev.state_fingering[:, None], cur.state_fingering[None, :]]
    return MOVE_COST * move + CUT_COST * cut


def assign_positions(notes, fixes: Sequence[PositionFix] = (),
                     tuning: Sequence[int] = STANDARD_TUNING) -> list[TabNote]:
    """String and fret for each note, in onset order."""
    # Every event has at least one fingering, if only the empty one.
    events = [_Event(group, fixes, tuning) for group in group_events(notes)]
    if not events:
        return []

    cost = events[0].state_cost
    back = []
    for prev, cur in zip(events, events[1:]):
        total = cost[:, None] + _transition(prev, cur)
        back.append(np.argmin(total, axis=0))
        cost = total.min(axis=0) + cur.state_cost
    state = int(np.argmin(cost))
    chosen = [0] * len(events)
    for e in range(len(events) - 1, -1, -1):
        chosen[e] = state
        if e > 0:
            state = int(back[e - 1][state])

    result = []
    for event, state in zip(events, chosen):
        fingering = event.fingerings[event.state_fingering[state]]
        hand = event.state_hand[state]
        placed = {}
        for i, string, fret in zip(fingering.notes, fingering.strings, fingering.frets):
            placed[i] = (string, fret, True)
        left_out = event.dropped | (set(event.members) - set(fingering.notes))
        for i in left_out:
            note = event.all_notes[i]
            options = positions(note.pitch, tuning)
            if i in event.fixed:
                options = [p for p in options if p.string == event.fixed[i]]
            # Out of the fingering: shown where the hand is, flagged.
            best = min(options, key=lambda p: abs(p.fret - (hand + MAX_SPAN / 2)))
            placed[i] = (best.string, best.fret, False)
        for i, note in enumerate(event.all_notes):
            string, fret, playable = placed.get(i, (None, None, False))
            result.append(TabNote(
                note.onset, note.offset, note.pitch, note.score,
                string, fret, playable, i in event.fixed,
            ))
    return result


def string_names(tuning: Sequence[int] = STANDARD_TUNING) -> list[str]:
    """Tab labels from string 1 down: e B G D A E in standard tuning."""
    names = [NOTE_NAMES[p % 12] for p in tuning]
    lowest = min(range(len(tuning)), key=lambda i: tuning[i])
    return [n.lower() if i == 0 and n == names[lowest] else n for i, n in enumerate(names)]
