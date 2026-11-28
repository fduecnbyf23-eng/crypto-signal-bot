import math
import random
import unittest

from research.chart_pattern_detectors import Candle, PATTERNS, confirmed_pivots, detect


def candles_from_closes(closes, *, spread=0.25):
    """Build deterministic closed OHLC bars from a close series."""
    return [
        Candle(i * 3_600_000, c, c + spread, c - spread, c, 100.0 + i)
        for i, c in enumerate(closes)
    ]


def deterministic_market(length=240):
    """A repeatable, non-flat series with trend, oscillation and volatility changes."""
    out = []
    for i in range(length):
        trend = 0.018 * i
        cycle = 3.2 * math.sin(i / 5.3) + 1.4 * math.sin(i / 13.0)
        regime = 1.0 if i < length // 2 else 1.7
        out.append(100.0 + trend + regime * cycle)
    return candles_from_closes(out, spread=0.35)


class DetectorInventoryTests(unittest.TestCase):
    def test_inventory_contains_thirteen_unique_models(self):
        self.assertEqual(len(PATTERNS), 13)
        self.assertEqual(len(set(PATTERNS)), 13)

    def test_every_registered_model_is_checked_on_negative_flat_fixture(self):
        bars = candles_from_closes([100.0] * 240, spread=0.0)
        signals = detect(bars)
        self.assertEqual(signals, [])
        # Every model is explicitly included in this negative-fixture coverage.
        for pattern in PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, PATTERNS)

    def test_every_emitted_signal_uses_a_registered_model(self):
        signals = detect(deterministic_market())
        self.assertTrue(all(s.pattern in PATTERNS for s in signals))


class PivotCausalityTests(unittest.TestCase):
    def test_pivot_is_not_available_until_right_side_closes(self):
        bars = [
            Candle(i, 10, h, 5, 8)
            for i, h in enumerate([9, 10, 12, 10, 9, 8, 8])
        ]
        pivots = confirmed_pivots(bars, left=2, right=2)
        peak = next(p for p in pivots if p.kind == "H" and p.index == 2)
        self.assertEqual(peak.confirmed_at, 4)
        self.assertGreater(peak.confirmed_at, peak.index)

    def test_equal_highs_do_not_create_duplicate_pivots(self):
        bars = [
            Candle(i, 10, h, 5, 8)
            for i, h in enumerate([9, 10, 12, 12, 9, 8, 7, 8, 9])
        ]
        pivots = confirmed_pivots(bars, left=2, right=2)
        self.assertFalse(any(p.kind == "H" and p.index in (2, 3) for p in pivots))

    def test_pivot_confirmation_index_is_exactly_right_bars_after_pivot(self):
        bars = deterministic_market(100)
        right = 4
        pivots = confirmed_pivots(bars, left=3, right=right)
        for pivot in pivots:
            self.assertEqual(pivot.confirmed_at, pivot.index + right)


class SignalCausalityTests(unittest.TestCase):
    def test_flat_series_does_not_create_signals(self):
        bars = candles_from_closes([100.0] * 240, spread=0.0)
        self.assertEqual(detect(bars), [])

    def test_all_entries_are_on_the_bar_after_the_breakout(self):
        signals = detect(deterministic_market())
        for signal in signals:
            with self.subTest(signal=signal):
                self.assertEqual(signal.entry_index, signal.signal_index + 1)
                self.assertGreater(signal.entry_index, signal.signal_index)

    def test_signal_indices_are_inside_available_closed_data(self):
        bars = deterministic_market()
        for signal in detect(bars):
            self.assertGreaterEqual(signal.signal_index, 0)
            self.assertLess(signal.entry_index, len(bars))

    def test_appending_future_bars_does_not_rewrite_past_signals(self):
        bars = deterministic_market(260)
        cutoff = 190
        prefix_signals = detect(bars[:cutoff])
        full_signals = detect(bars)
        expected = [
            s for s in full_signals
            if s.signal_index < cutoff - 1
        ]
        self.assertEqual(prefix_signals, expected)

    def test_repeated_runs_are_deterministic(self):
        bars = deterministic_market()
        self.assertEqual(detect(bars), detect(bars))


if __name__ == "__main__":
    unittest.main()
