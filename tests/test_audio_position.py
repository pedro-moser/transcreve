from pathlib import Path
import sys
import unittest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.audio_service import _Block, heard_frame  # noqa: E402

# 2048 frames at 48 kHz, heard from stream time 10.0 on
BLOCK = 2048 / 48_000
FIRST = _Block(10.0, BLOCK, 48_000, 50_048)
SECOND = _Block(10.0 + BLOCK, BLOCK, 50_048, 52_096)


class HeardFrameTests(unittest.TestCase):
    def test_without_blocks_or_clock_the_playback_position_is_used(self):
        self.assertEqual(heard_frame([], 10.0, 1234.0), 1234.0)
        self.assertEqual(heard_frame([FIRST], 0.0, 1234.0), 1234.0)

    def test_moves_smoothly_inside_a_block(self):
        self.assertAlmostEqual(heard_frame([FIRST, SECOND], 10.0 + BLOCK / 4, 0), 48_512)
        self.assertAlmostEqual(heard_frame([FIRST, SECOND], 10.0 + BLOCK * 1.5, 0), 51_072)

    def test_before_anything_is_heard_it_waits_at_the_first_block(self):
        self.assertEqual(heard_frame([FIRST, SECOND], 9.9, 99_999), 48_000)

    def test_stops_at_the_end_of_the_last_block(self):
        self.assertEqual(heard_frame([FIRST], 11.0, 0), 50_048)

    def test_a_loop_jump_is_heard_when_its_block_plays(self):
        jump = _Block(10.0 + BLOCK, BLOCK, 4_800, 6_848)  # back to the loop start
        self.assertGreater(heard_frame([FIRST, jump], 10.0 + BLOCK * 0.9, 0), 49_000)
        self.assertLess(heard_frame([FIRST, jump], 10.0 + BLOCK * 1.1, 0), 6_848)


if __name__ == "__main__":
    unittest.main()
