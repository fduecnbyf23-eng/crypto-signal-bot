import unittest
from indicator_features import ema, rsi_wilder, atr_wilder, divergence_flags, build_features


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
