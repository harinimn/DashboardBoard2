"""Check the telemetry parser without needing the GUI or STM32 hardware."""

import unittest
from telemetry import Telemetry, Lines


class ProtocolTests(unittest.TestCase):
    def test_old_and_batched_messages(self):
        d = Telemetry()

        # Both the old single-field format and batched messages should work.
        self.assertTrue(d.feed('pwr=12000', 0))
        self.assertTrue(d.feed('avg_pwr=8000,mode=1', 0))

        # At one second, these readings should still be fresh.
        self.assertEqual(d.get('pwr', 1), 12000)
        self.assertEqual(d.get('avg_pwr', 1), 8000)

    def test_individual_freshness(self):
        d = Telemetry()

        # Both fields arrive initially, but only power gets another update.
        d.feed('pwr=12000,fault_bms=1', 0)
        d.feed('pwr=14000', 1)

        # The old fault reading should expire even though power is still fresh.
        self.assertIsNone(d.get('fault_bms', 2))
        self.assertEqual(d.get('pwr', 2), 14000)

    def test_bad_frame_does_not_partially_update(self):
        d = Telemetry()

        # Try invalid numbers, text where a number belongs, and a broken message.
        for line in [
            'pwr=12,avg_pwr=nan',
            'pwr=inf',
            'pwr=12,mode=no',
            'garbage'
        ]:
            self.assertFalse(d.feed(line, 0))

        # Even the valid first field in a bad batch shouldn't have been saved.
        self.assertEqual(d.values, {})

    def test_fragments_and_overflow(self):
        frames = Lines()

        # The first read ends halfway through a message, so nothing is ready yet.
        self.assertEqual(frames.feed(b'pwr=1'), [])

        # The next read finishes that message and includes another complete one.
        self.assertEqual(
            frames.feed(b'200\r\navg_pwr=900\n'),
            ['pwr=1200', 'avg_pwr=900']
        )

        # An oversized message should be dropped, then normal parsing resumes.
        self.assertEqual(
            frames.feed(b'x' * 3000 + b'\npwr=2\n'),
            ['pwr=2']
        )

        # A bad byte should only affect its own message.
        self.assertEqual(
            frames.feed(b'\xff\npwr=3\n'),
            ['pwr=3']
        )


# Run all the checks when this file is executed directly.
if __name__ == '__main__':
    unittest.main()