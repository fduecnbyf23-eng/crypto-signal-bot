import unittest

from research.chart_pattern_detectors import Candle, PATTERNS, confirmed_pivots, detect


class DetectorCausalityTests(unittest.TestCase):
    def test_inventory_contains_all_thirteen_models(self):
        self.assertEqual(len(PATTERNS), 13)
        self.assertEqual(len(set(PATTERNS)), 13)

    def test_pivot_is_not_available_until_right_side_closes(self):
        bars = [
            Candle(i, 10, h, 5, 8)
            for i, h in enumerate([9, 10, 12, 10, 9, 8, 8])
        ]
        pivots = confirmed_pivots(bars, left=2, right=2)
        peak = next(p for p in pivots if p.kind == "H" and p.index == 2)
        self.assertEqual(peak.confirmed_at, 4)
        self.assertGreater(peak.confirmed_at, peak.index)

    def test_detect_returns_only_next_bar_entries(self):
        # A flat synthetic series is not expected to create a breakout signal.
        bars = [Candle(i * 3600000, 100, 101, 99, 100) for i in range(100)]
        signals = detect(bars)
        self.assertEqual(signals, [])
        self.assertTrue(all(s.entry_index == s.signal_index + 1 for s in signals))


if __name__ == "__main__":
    unittest.main()
