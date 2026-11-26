#!/usr/bin/env python3
"""Research-only indicator feature builder. Creates features, never trades."""
import argparse
import csv
import math
import os
from datetime import datetime, timezone


def ema(values, period):
    out = [None] * len(values)
    if len(values) < period:
        return out
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    alpha = 2.0 / (period + 1.0)
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1.0 - alpha) * prev
        out[i] = prev
    return out


def rsi_wilder(values, period=14):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period

    def value(g, loss):
        if loss == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / loss)

    out[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
        out[i] = value(avg_gain, avg_loss)
    return out


def atr_wilder(high, low, close, period=14):
    tr = []
    for i in range(len(close)):
        tr.append(high[i] - low[i] if i == 0 else max(
            high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1])))
    out = [None] * len(close)
    if len(close) < period:
        return out
    prev = sum(tr[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(close)):
        prev = (prev * (period - 1) + tr[i]) / period
        out[i] = prev
    return out


def rolling_mean(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i-period+1:i+1]) / period
    return out


def rolling_std(values, period):
    out = [None] * len(values)
    for i in range(period - 1, len(values)):
        w = values[i-period+1:i+1]
        mean = sum(w) / period
        out[i] = math.sqrt(sum((x-mean)**2 for x in w) / period)
    return out


def macd(values):
    fast, slow = ema(values, 12), ema(values, 26)
    line = [None if fast[i] is None or slow[i] is None else fast[i]-slow[i]
            for i in range(len(values))]
    valid = [x for x in line if x is not None]
    sig_valid = ema(valid, 9)
    signal = [None] * len(values)
    j = 0
    for i, x in enumerate(line):
        if x is not None:
            signal[i] = sig_valid[j]
            j += 1
    hist = [None if line[i] is None or signal[i] is None else line[i]-signal[i]
            for i in range(len(values))]
    return line, signal, hist


def percentile_rank(value, history):
    if not history:
        return None
    return sum(1 for x in history if x <= value) / len(history)


def divergence_flags(high, low, rsi, left=3, right=3, max_gap=60):
    """Confirmed pivots: signal is emitted at confirmation, not pivot timestamp."""
    n = len(low)
    bull, bear = [False]*n, [False]*n
    lows, highs = [], []
    for i in range(left + right, n):
        p = i - right
        if rsi[p] is None:
            continue
        if all(low[p] < low[j] for j in range(p-left,p+right+1) if j != p):
            if lows:
                q = lows[-1]
                if 0 < p-q <= max_gap and low[p] < low[q] and rsi[p] > rsi[q]:
                    bull[i] = True
            lows.append(p)
        if all(high[p] > high[j] for j in range(p-left,p+right+1) if j != p):
            if highs:
                q = highs[-1]
                if 0 < p-q <= max_gap and high[p] > high[q] and rsi[p] < rsi[q]:
                    bear[i] = True
            highs.append(p)
    return bull, bear


def vpvr_close_weighted(high, low, close, quote_volume, lookback=100, bins=24):
    """Approximation: each candle's quote volume is assigned to its close-price bin."""
    n = len(close)
    poc, val, vah = [None]*n, [None]*n, [None]*n
    for i in range(lookback-1, n):
        start = i-lookback+1
        pmin, pmax = min(low[start:i+1]), max(high[start:i+1])
        if pmax <= pmin:
            poc[i] = val[i] = vah[i] = close[i]
            continue
        step = (pmax-pmin)/bins
        hist = [0.0]*bins
        for j in range(start, i+1):
            k = min(bins-1, max(0, int((close[j]-pmin)/step)))
            hist[k] += max(0.0, quote_volume[j])
        peak = max(range(bins), key=lambda k: hist[k])
        left = right = peak
        total, target = hist[peak], sum(hist)*0.70
        while total < target and (left > 0 or right < bins-1):
            lv = hist[left-1] if left > 0 else -1
            rv = hist[right+1] if right < bins-1 else -1
            if rv > lv:
                right += 1
                total += hist[right]
            else:
                left -= 1
                total += hist[left]
        poc[i] = pmin + (peak+0.5)*step
        val[i] = pmin + left*step
        vah[i] = pmin + (right+1)*step
    return poc, val, vah


def build_features(rows):
    if not rows:
        return []
    ts = [int(r['timestamp_ms']) for r in rows]
    high = [float(r['high']) for r in rows]
    low = [float(r['low']) for r in rows]
    close = [float(r['close']) for r in rows]
    quote = [float(r['volume_quote']) for r in rows]
    e20, e50, e200 = ema(close,20), ema(close,50), ema(close,200)
    rsi, atr = rsi_wilder(close,14), atr_wilder(high,low,close,14)
    ml, ms, mh = macd(close)
    mid, sd = rolling_mean(close,20), rolling_std(close,20)
    upper = [None if mid[i] is None else mid[i]+2*sd[i] for i in range(len(close))]
    lower = [None if mid[i] is None else mid[i]-2*sd[i] for i in range(len(close))]
    width = [None if mid[i] in (None,0) else (upper[i]-lower[i])/mid[i]
             for i in range(len(close))]
    qmean = rolling_mean(quote,20)
    bull_div, bear_div = divergence_flags(high,low,rsi)
    poc, val, vah = vpvr_close_weighted(high,low,close,quote)
    vwap, day_key, sum_q, sum_pq = [None]*len(close), None, 0.0, 0.0
    for i, stamp in enumerate(ts):
        day = datetime.fromtimestamp(stamp/1000,timezone.utc).date()
        if day != day_key:
            day_key, sum_q, sum_pq = day, 0.0, 0.0
        sum_q += quote[i]
        sum_pq += ((high[i]+low[i]+close[i])/3.0)*quote[i]
        vwap[i] = sum_pq/sum_q if sum_q else None

    ranks, squeezes = [None]*len(close), [False]*len(close)
    for i in range(len(close)):
        hist = [x for x in width[max(0,i-120):i] if x is not None]
        ranks[i] = percentile_rank(width[i],hist) if width[i] is not None and len(hist)>=60 else None
        squeezes[i] = bool(ranks[i] is not None and ranks[i]<=0.20)

    out = []
    for i in range(len(close)):
        vol_ratio = quote[i]/qmean[i] if qmean[i] else None
        ready = all(x is not None for x in
                    (e20[i],e50[i],e200[i],rsi[i],atr[i],ml[i],ms[i],upper[i],lower[i]))
        prev_ready = i>0 and all(x is not None for x in (ml[i-1],ms[i-1],vwap[i-1]))
        bull_stack = bool(ready and close[i]>e20[i]>e50[i]>e200[i])
        bear_stack = bool(ready and close[i]<e20[i]<e50[i]<e200[i])
        ema_long = bool(ready and bull_stack and low[i]<=e20[i] and close[i]>e20[i])
        ema_short = bool(ready and bear_stack and high[i]>=e20[i] and close[i]<e20[i])
        macd_up = bool(prev_ready and ml[i]>ms[i] and ml[i-1]<=ms[i-1])
        macd_down = bool(prev_ready and ml[i]<ms[i] and ml[i-1]>=ms[i-1])
        prior_squeeze = any(squeezes[max(0,i-10):i])
        bb_up = bool(upper[i] is not None and close[i]>upper[i] and prior_squeeze)
        bb_down = bool(lower[i] is not None and close[i]<lower[i] and prior_squeeze)
        same_utc_day = bool(i>0 and datetime.fromtimestamp(ts[i]/1000,timezone.utc).date()
                            == datetime.fromtimestamp(ts[i-1]/1000,timezone.utc).date())
        vw_long = bool(same_utc_day and low[i]<=vwap[i] and close[i]>vwap[i] and close[i-1]<=vwap[i-1])
        vw_short = bool(same_utc_day and high[i]>=vwap[i] and close[i]<vwap[i] and close[i-1]>=vwap[i-1])
        rsi_up_30 = bool(i>0 and rsi[i-1] is not None and rsi[i] is not None and rsi[i-1]<=30 and rsi[i]>30)
        rsi_down_70 = bool(i>0 and rsi[i-1] is not None and rsi[i] is not None and rsi[i-1]>=70 and rsi[i]<70)
        vp_long = bool(i>0 and val[i-1] is not None and low[i]<=val[i-1] and close[i]>val[i-1])
        vp_short = bool(i>0 and vah[i-1] is not None and high[i]>=vah[i-1] and close[i]<vah[i-1])
        out.append({
            'timestamp_ms':ts[i], 'close':close[i], 'ema20':e20[i], 'ema50':e50[i], 'ema200':e200[i],
            'rsi14':rsi[i], 'atr14':atr[i], 'macd':ml[i], 'macd_signal':ms[i], 'macd_hist':mh[i],
            'bb_upper':upper[i], 'bb_mid':mid[i], 'bb_lower':lower[i], 'bb_width':width[i],
            'bb_width_percentile':ranks[i], 'volume_quote':quote[i], 'volume_quote_sma20':qmean[i],
            'volume_ratio':vol_ratio, 'vwap_utc_day':vwap[i], 'vpvr_poc_100':poc[i],
            'vpvr_val_100':val[i], 'vpvr_vah_100':vah[i],
            'vpvr_bounce_long':vp_long, 'vpvr_bounce_short':vp_short,
            'ema_bull_stack':bull_stack, 'ema_bear_stack':bear_stack,
            'ema20_bounce_long':ema_long, 'ema20_bounce_short':ema_short,
            'rsi_oversold':bool(rsi[i] is not None and rsi[i]<30),
            'rsi_overbought':bool(rsi[i] is not None and rsi[i]>70),
            'rsi_cross_up_30':rsi_up_30, 'rsi_cross_down_70':rsi_down_70,
            'rsi_bullish_divergence':bull_div[i], 'rsi_bearish_divergence':bear_div[i],
            'volume_confirm':bool(vol_ratio is not None and vol_ratio>=1.5),
            'bb_squeeze':squeezes[i], 'bb_breakout_up':bb_up, 'bb_breakout_down':bb_down,
            'macd_cross_up':macd_up, 'macd_cross_down':macd_down,
            'vwap_bounce_long':vw_long, 'vwap_bounce_short':vw_short,
            'ema_macd_long':bool(bull_stack and macd_up),
            'ema_macd_short':bool(bear_stack and macd_down),
            'rsi_volume_long':bool((rsi_up_30 or bull_div[i]) and vol_ratio is not None and vol_ratio>=1.5),
            'rsi_volume_short':bool((rsi_down_70 or bear_div[i]) and vol_ratio is not None and vol_ratio>=1.5),
            'vwap_ema_long':bool(bull_stack and vw_long),
            'vwap_ema_short':bool(bear_stack and vw_short)
        })
    return out


def apply_timeframe_scope(features, timeframe):
    """Blank indicator families on timeframes not declared in the frozen spec."""
    scopes = {
        'ema': {'1H', '4H', '1Dutc'},
        'rsi': {'15m', '1H', '4H'},
        'volume': {'15m', '1H', '4H'},
        'vpvr': {'1H', '4H'},
        'bb': {'1H', '4H'},
        'macd': {'4H', '1Dutc'},
        'vwap': {'15m', '1H'},
        'ema_macd': {'4H', '1Dutc'},
        'rsi_volume': {'15m', '1H', '4H'},
        'vwap_ema': {'1H'},
    }
    fields = {
        'ema': ['ema20','ema50','ema200','ema_bull_stack','ema_bear_stack',
                'ema20_bounce_long','ema20_bounce_short'],
        'rsi': ['rsi14','rsi_oversold','rsi_overbought','rsi_cross_up_30','rsi_cross_down_70',
                'rsi_bullish_divergence','rsi_bearish_divergence'],
        'volume': ['volume_quote_sma20','volume_ratio','volume_confirm'],
        'vpvr': ['vpvr_poc_100','vpvr_val_100','vpvr_vah_100','vpvr_bounce_long','vpvr_bounce_short'],
        'bb': ['bb_upper','bb_mid','bb_lower','bb_width','bb_width_percentile',
               'bb_squeeze','bb_breakout_up','bb_breakout_down'],
        'macd': ['macd','macd_signal','macd_hist','macd_cross_up','macd_cross_down'],
        'vwap': ['vwap_utc_day','vwap_bounce_long','vwap_bounce_short'],
        'ema_macd': ['ema_macd_long','ema_macd_short'],
        'rsi_volume': ['rsi_volume_long','rsi_volume_short'],
        'vwap_ema': ['vwap_ema_long','vwap_ema_short'],
    }
    for family, allowed in scopes.items():
        if timeframe not in allowed:
            for row in features:
                for field in fields[family]:
                    row[field] = False if field in {
                        'ema_bull_stack','ema_bear_stack','ema20_bounce_long',
                        'ema20_bounce_short','rsi_oversold','rsi_overbought',
                        'rsi_bullish_divergence','rsi_bearish_divergence',
                        'volume_confirm','bb_squeeze','bb_breakout_up',
                        'bb_breakout_down','macd_cross_up','macd_cross_down',
                        'vwap_bounce_long','vwap_bounce_short','vpvr_bounce_long',
                        'vpvr_bounce_short','ema_macd_long','ema_macd_short',
                        'rsi_volume_long','rsi_volume_short','vwap_ema_long','vwap_ema_short'
                    } else None
    return features


def process_file(source, destination):
    with open(source,newline='',encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    features = build_features(rows)
    timeframe = os.path.basename(source).rsplit('_', 1)[-1].removesuffix('.csv')
    features = apply_timeframe_scope(features, timeframe)
    if not features:
        raise ValueError('No candles in '+source)
    os.makedirs(os.path.dirname(destination) or '.',exist_ok=True)
    with open(destination,'w',newline='',encoding='utf-8') as f:
        writer = csv.DictWriter(f,fieldnames=list(features[0]))
        writer.writeheader()
        writer.writerows(features)
    return len(features)


def main():
    p = argparse.ArgumentParser(description='Build frozen indicator features; no trades are simulated.')
    p.add_argument('--input-dir',default='research-data')
    p.add_argument('--output-dir',default='research-features')
    p.add_argument('--markets',choices=['spot','swap','both'],default='both')
    args = p.parse_args()
    os.makedirs(args.output_dir,exist_ok=True)
    symbols, tfs, markets = ['BTC','ETH','SOL','BNB','XRP'], ['15m','1H','4H','1Dutc'], []
    if args.markets in ('spot','both'): markets.append('')
    if args.markets in ('swap','both'): markets.append('_SWAP')
    total = 0
    for symbol in symbols:
        for market in markets:
            for tf in tfs:
                src = os.path.join(args.input_dir,f'{symbol}_USDT{market}_{tf}.csv')
                if not os.path.exists(src):
                    continue
                dst = os.path.join(args.output_dir,f'{symbol}_USDT{market}_{tf}_features.csv')
                count = process_file(src,dst)
                total += count
                print(f'{src}: {count} feature rows -> {dst}',flush=True)
    if total == 0:
        raise SystemExit('No matching candle CSV files found')
    print(f'Completed {total} feature rows. No trades or orders were generated.')


if __name__ == '__main__':
    main()
