import unittest

from chart_pattern_paper import settle
from research.chart_pattern_detectors import Candle


class PaperSettlementTests(unittest.TestCase):
    def make_trade(self):
        return {
            "symbol": "BTC-USDT-SWAP",
            "timeframe": "1H",
            "direction": "SHORT",
            "entry_ts": 1000,
            "entry": 100.0,
            "stop": 110.0,
            "target": 80.0,
            "risk": 10.0,
            "status": "OPEN",
            "realized_r": None,
        }

    def test_trade_stays_open_if_no_level_is_hit(self):
        trade = self.make_trade()
        settle([trade], "BTC-USDT-SWAP", "1H", [
            Candle(1000, 100, 105, 95, 101),
            Candle(2000, 101, 108, 90, 99),
        ])
        self.assertEqual(trade["status"], "OPEN")
        self.assertIsNone(trade["realized_r"])

    def test_target_closes_short_trade_as_win(self):
        trade = self.make_trade()
        settle([trade], "BTC-USDT-SWAP", "1H", [
            Candle(1000, 100, 101, 79, 82),
        ])
        self.assertEqual(trade["status"], "WIN")
        self.assertEqual(trade["exit_price"], 80.0)
        self.assertAlmostEqual(trade["gross_r"], 2.0)
        self.assertLess(trade["realized_r"], 2.0)

    def test_stop_wins_if_stop_and_target_touch_same_bar(self):
        trade = self.make_trade()
        settle([trade], "BTC-USDT-SWAP", "1H", [
            Candle(1000, 100, 111, 79, 90),
        ])
        self.assertEqual(trade["status"], "LOSS")
        self.assertEqual(trade["exit_price"], 110.0)


if __name__ == "__main__":
    unittest.main()
