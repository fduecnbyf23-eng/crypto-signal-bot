import unittest

from backtest_frozen_indicators import simulate, funding_r_for_interval, HOLDOUT_1Y


def candle(ts, op=100, hi=101, lo=99, close=100):
    return {
        "timestamp_ms": str(ts), "open": str(op), "high": str(hi),
        "low": str(lo), "close": str(close)
    }


class FrozenBacktestTests(unittest.TestCase):
    def test_stop_first_when_stop_and_target_hit_same_candle(self):
        step = 900_000
        rows = [candle(0), candle(step, hi=104, lo=97), candle(2*step)]
        features = [
            {"atr14": 1.0, "go_long": True, "go_short": False, "rsi14": 50},
            {"atr14": 1.0, "go_long": False, "go_short": False, "rsi14": 50},
            {"atr14": 1.0, "go_long": False, "go_short": False, "rsi14": 50},
        ]
        trades, invalid = simulate(
            rows, features, "15m", "go_long", "go_short", "SPOT", "BTC",
            "test", "base", "holdout", None, None, {}, None, True
        )
        self.assertEqual(invalid, 0)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "STOP")
        self.assertLess(float(trades[0]["net_R"]), -1.0)

    def test_rsi_exit_occurs_at_next_candle_open(self):
        step = 900_000
        rows = [
            candle(0),
            candle(step, hi=101, lo=99, close=100),
            candle(2*step, op=102, hi=103, lo=101, close=102),
            candle(3*step)
        ]
        features = [
            {"atr14": 1.0, "go_long": True, "go_short": False, "rsi14": 50},
            {"atr14": 1.0, "go_long": False, "go_short": False, "rsi14": 72},
            {"atr14": 1.0, "go_long": False, "go_short": False, "rsi14": 65},
            {"atr14": 1.0, "go_long": False, "go_short": False, "rsi14": 60},
        ]
        trades, _ = simulate(
            rows, features, "15m", "go_long", "go_short", "SPOT", "BTC",
            "rsi_test", "rsi_extreme", "holdout", None, None, {}, None, True
        )
        self.assertEqual(trades[0]["exit_reason"], "RSI_EXTREME_NEXT_OPEN")
        self.assertEqual(float(trades[0]["exit_price"]), 102.0)

    def test_funding_is_applied_only_after_entry(self):
        interval = 8 * 60 * 60 * 1000
        rates = {0: 0.02, interval: 0.01}
        value, valid = funding_r_for_interval(
            rates, 0, 1, 100.0, 1.5, 60 * 60 * 1000, 9 * 60 * 60 * 1000
        )
        self.assertTrue(valid)
        self.assertAlmostEqual(value, -0.01 * 100.0 / 1.5)

    def test_missing_funding_record_invalidates_interval(self):
        interval = 8 * 60 * 60 * 1000
        rates = {0: 0.02}
        value, valid = funding_r_for_interval(
            rates, 0, 1, 100.0, 1.5, 60 * 60 * 1000, 9 * 60 * 60 * 1000
        )
        self.assertFalse(valid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
