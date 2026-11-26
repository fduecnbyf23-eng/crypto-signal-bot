import unittest
from indicator_features import ema, rsi_wilder, atr_wilder, divergence_flags, build_features, apply_timeframe_scope


class IndicatorFeatureTests(unittest.TestCase):
    def test_ema_seed_and_smoothing(self):
        got = ema([1,2,3,4,5],3)
        self.assertIsNone(got[1])
        self.assertAlmostEqual(got[2],2.0)
        self.assertAlmostEqual(got[3],3.0)

    def test_rsi_strong_uptrend(self):
        got = rsi_wilder(list(range(20)),14)
        self.assertAlmostEqual(got[-1],100.0)

    def test_atr_constant_range(self):
        got = atr_wilder([11.0]*20,[9.0]*20,[10.0]*20,14)
        self.assertAlmostEqual(got[-1],2.0)

    def test_divergence_only_after_pivot_confirmation(self):
        low = [10,9,8,7,8,9,8,7,6,8,9]
        high = [x+2 for x in low]
        rsi = [40,41,42,30,40,41,42,43,35,45,46]
        bull,bear = divergence_flags(high,low,rsi,left=1,right=1,max_gap=10)
        self.assertFalse(any(bull[:9]))
        self.assertTrue(bull[9])
        self.assertFalse(any(bear))

    def test_equal_low_ties_are_not_divergence_pivots(self):
        low = [10, 8, 8, 9, 10]
        high = [x+2 for x in low]
        rsi = [40, 30, 30, 40, 45]
        bull, bear = divergence_flags(high, low, rsi, left=1, right=1, max_gap=10)
        self.assertFalse(any(bull))
        self.assertFalse(any(bear))

    def test_daily_scope_disables_intraday_only_families(self):
        features = [{
            'ema20': 100.0, 'ema_bull_stack': True,
            'rsi14': 25.0, 'rsi_oversold': True, 'rsi_overbought': False,
            'volume_ratio': 2.0, 'volume_confirm': True,
            'vpvr_poc_100': 99.0, 'bb_upper': 110.0, 'bb_squeeze': True,
            'macd': 1.0, 'macd_cross_up': True,
            'vwap_utc_day': 101.0, 'vwap_bounce_long': True,
            'rsi_cross_up_30': True, 'vpvr_bounce_long': True,
            'ema_macd_long': True, 'rsi_volume_long': True, 'vwap_ema_long': True,
        }]
        scoped = apply_timeframe_scope(features, '1Dutc')
        row = scoped[0]
        self.assertEqual(row['ema20'], 100.0)
        self.assertEqual(row['macd'], 1.0)
        self.assertIsNone(row['rsi14'])
        self.assertIsNone(row['volume_ratio'])
        self.assertIsNone(row['vpvr_poc_100'])
        self.assertIsNone(row['bb_upper'])
        self.assertIsNone(row['vwap_utc_day'])
        self.assertFalse(row['vwap_bounce_long'])
        self.assertFalse(row['rsi_cross_up_30'])
        self.assertFalse(row['vpvr_bounce_long'])
        self.assertTrue(row['ema_macd_long'])
        self.assertFalse(row['rsi_volume_long'])
        self.assertFalse(row['vwap_ema_long'])

    def test_vwap_bounce_does_not_cross_utc_day_reset(self):
        day_start = 1764115200000  # 2025-11-26 00:00 UTC
        rows = [
            {'timestamp_ms':str(day_start-900000),'open':'1','high':'20','low':'0',
             'close':'1','volume_quote':'1','confirm':'1'},
            {'timestamp_ms':str(day_start),'open':'15','high':'20','low':'0',
             'close':'15','volume_quote':'1','confirm':'1'},
        ]
        features = build_features(rows)
        self.assertFalse(features[1]['vwap_bounce_long'])
        self.assertFalse(features[1]['vwap_bounce_short'])

    def test_rsi_overbought_is_exposed(self):
        rows = []
        for i in range(230):
            close = 100+i
            rows.append({'timestamp_ms':str(1764000000000+i*900000),'open':str(close),
                         'high':str(close+1),'low':str(close-1),'close':str(close),
                         'volume_quote':'1000','confirm':'1'})
        features = build_features(rows)
        self.assertTrue(features[-1]['rsi_overbought'])

    def test_prefix_is_independent_of_future_rows(self):
        rows = []
        for i in range(260):
            close = 100+i*0.1
            rows.append({'timestamp_ms':str(1764000000000+i*900000),'open':str(close),
                         'high':str(close+1),'low':str(close-1),'close':str(close+0.2),
                         'volume_quote':str(1000+i),'confirm':'1'})
        altered = [dict(x) for x in rows]
        for i in range(220,len(altered)):
            altered[i]['close'] = str(float(altered[i]['close'])*0.5)
            altered[i]['high'] = str(float(altered[i]['high'])*0.5)
            altered[i]['low'] = str(float(altered[i]['low'])*0.5)
        a,b = build_features(rows),build_features(altered)
        for i in range(220):
            for key in ('ema20','rsi14','vpvr_poc_100','bb_breakout_up'):
                self.assertEqual(a[i][key],b[i][key])


if __name__ == '__main__':
    unittest.main(verbosity=2)
