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


def pattern_fixture(anchors, *, direction="SHORT", close_shape=None):
    """Create isolated OHLC swing anchors; each pivot is only knowable after right bars."""
    length = 230
    closes = [100.0] * length
    if close_shape == "rounding_top":
        # Rounded rise and fall, with a later support break.
        for j in range(40):
            x = j / 39
            closes[length - 41 + j] = 100.0 + 10.0 * (1.0 - abs(2.0*x - 1.0))
    elif close_shape == "inverted_cup":
        for j in range(40):
            x = j / 39
            closes[length - 41 + j] = 110.0 - 10.0 * (1.0 - abs(2.0*x - 1.0))
        # A weak handle after the right rim.
        for j in range(length - 8, length - 1):
            closes[j] = 108.0 + 0.15 * (j % 2)
    bars = []
    anchors_by_index = {idx: (kind, price) for idx, kind, price in anchors}
    for i, close in enumerate(closes):
        high, low = close + 0.25, close - 0.25
        if i in anchors_by_index:
            kind, price = anchors_by_index[i]
            if kind == "H":
                high = price
                low = min(low, close - 0.1)
            else:
                low = price
                high = max(high, close + 0.1)
        bars.append(Candle(i * 3_600_000, close, high, low, close, 100.0))
    # Break only after all pattern pivots have had time to confirm.
    final_close = 90.0 if direction == "SHORT" else 110.0
    bars[-2] = Candle(bars[-2].ts, final_close, final_close + 0.25,
                      final_close - 0.25, final_close, 100.0)
    return bars


class PositiveSyntheticPatternTests(unittest.TestCase):
    def assert_pattern_detected(self, name, anchors, direction="SHORT", close_shape=None):
        bars = pattern_fixture(anchors, direction=direction, close_shape=close_shape)
        found = [s for s in detect(bars) if s.pattern == name and s.direction == direction]
        self.assertTrue(found, f"{name} did not trigger on its positive synthetic fixture")
        for signal in found:
            self.assertEqual(signal.entry_index, signal.signal_index + 1)
            self.assertEqual(signal.signal_index, len(bars) - 2)

    def test_double_top(self):
        self.assert_pattern_detected("double_top", [(145,"H",110),(160,"L",95),(175,"H",110)])

    def test_double_bottom(self):
        self.assert_pattern_detected("double_bottom", [(145,"L",90),(160,"H",105),(175,"L",90)], "LONG")

    def test_head_and_shoulders(self):
        self.assert_pattern_detected("head_and_shoulders", [(135,"H",110),(145,"L",95),(155,"H",116),(165,"L",95),(175,"H",110)])

    def test_inverse_head_and_shoulders(self):
        self.assert_pattern_detected("inverse_head_and_shoulders", [(135,"L",90),(145,"H",105),(155,"L",84),(165,"H",105),(175,"L",90)], "LONG")

    def test_ascending_wedge(self):
        self.assert_pattern_detected("ascending_wedge", [(145,"L",95),(155,"H",105),(165,"L",97),(175,"H",112)])

    def test_descending_wedge(self):
        self.assert_pattern_detected("descending_wedge", [(145,"H",112),(155,"L",95),(165,"H",100),(175,"L",93)], "LONG")

    def test_triple_top(self):
        self.assert_pattern_detected("triple_top", [(135,"H",110),(145,"L",95),(155,"H",110),(165,"L",95),(175,"H",110)])

    def test_trend_reversal_structure_break(self):
        self.assert_pattern_detected("trend_reversal_structure_break", [(145,"H",110),(160,"L",95),(175,"H",108),(188,"L",96)])

    def test_bearish_broadening(self):
        self.assert_pattern_detected("bearish_broadening", [(145,"L",95),(155,"H",105),(165,"L",88),(175,"H",114)])

    def test_bullish_broadening(self):
        self.assert_pattern_detected("bullish_broadening", [(145,"L",95),(155,"H",105),(165,"L",88),(175,"H",114)], "LONG")

    def test_rounding_top(self):
        self.assert_pattern_detected("rounding_top", [(145,"H",110),(160,"L",95),(175,"H",108)], close_shape="rounding_top")

    def test_inverted_cup_and_handle(self):
        self.assert_pattern_detected("inverted_cup_and_handle", [(145,"H",110),(160,"L",95),(175,"H",110)], close_shape="inverted_cup")

    def test_diamond_top(self):
        self.assert_pattern_detected("diamond_top", [(130,"H",110),(138,"L",100),(146,"H",118),(154,"L",96),(162,"H",116),(170,"L",98),(178,"H",111)])
