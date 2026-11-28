#!/usr/bin/env python3
"""Causal OHLCV chart-pattern detectors for isolated research.

Only closed candles are accepted. A pivot at i is exposed at i + right_bars,
never at i. This module emits candidate breakouts; it does not place orders.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Optional

PATTERNS = (
    "double_top", "head_and_shoulders", "ascending_wedge", "double_bottom",
    "inverse_head_and_shoulders", "descending_wedge", "triple_top",
    "trend_reversal_structure_break", "bearish_broadening", "rounding_top",
    "inverted_cup_and_handle", "diamond_top", "bullish_broadening",
)


@dataclass(frozen=True)
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Pivot:
    index: int
    confirmed_at: int
    kind: str  # "H" or "L"
    price: float


@dataclass(frozen=True)
class Signal:
    pattern: str
    direction: str  # LONG / SHORT
    signal_index: int
    entry_index: int
    boundary: float
    invalidation: float
    target_r: float
    pivot_indices: tuple[int, ...]
    note: str


def _atr(candles: list[Candle], end: int, period: int = 14) -> Optional[float]:
    start = max(1, end - period + 1)
    if end - start + 1 < min(period, 5):
        return None
    tr = []
    for j in range(start, end + 1):
        prev = candles[j - 1].close
        c = candles[j]
        tr.append(max(c.high - c.low, abs(c.high - prev), abs(c.low - prev)))
    return sum(tr) / len(tr) if tr else None


def confirmed_pivots(candles: Iterable[Candle], left: int = 3, right: int = 3) -> list[Pivot]:
    """Return pivots with their availability index; ties are resolved deterministically."""
    bars = list(candles)
    out: list[Pivot] = []
    for i in range(left, len(bars) - right):
        window = bars[i-left:i+right+1]
        hi, lo = bars[i].high, bars[i].low
        # Strict on at least one side; equal extrema do not create duplicate pivots.
        if hi == max(x.high for x in window) and sum(x.high == hi for x in window) == 1:
            out.append(Pivot(i, i + right, "H", hi))
        if lo == min(x.low for x in window) and sum(x.low == lo for x in window) == 1:
            out.append(Pivot(i, i + right, "L", lo))
    return sorted(out, key=lambda p: (p.confirmed_at, p.index, p.kind))


def _similar(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


def _line_value(p1: Pivot, p2: Pivot, at: int) -> float:
    if p2.index == p1.index:
        return p2.price
    return p1.price + (p2.price - p1.price) * (at - p1.index) / (p2.index - p1.index)


def detect(candles: Iterable[Candle], *, left: int = 3, right: int = 3,
           min_separation: int = 5, max_span: int = 120,
           tolerance_atr: float = 0.50, breakout_atr: float = 0.10,
           max_breakout_wait: int = 30, target_r: float = 2.0) -> list[Signal]:
    """Detect all configured patterns causally; one signal per pattern and bar."""
    bars = list(candles)
    pivots_all = confirmed_pivots(bars, left, right)
    signals: list[Signal] = []
    seen: set[tuple[str, int, str]] = set()

    for i in range(max(left + right + 14, 30), len(bars) - 1):
        atr = _atr(bars, i)
        if not atr or atr <= 0:
            continue
        tol, buf = tolerance_atr * atr, breakout_atr * atr
        ps = [p for p in pivots_all if p.confirmed_at <= i and i - p.index <= max_span]
        ps = ps[-12:]
        if len(ps) < 3:
            continue
        c = bars[i].close

        def emit(name: str, direction: str, boundary: float, extreme: float,
                 chosen: list[Pivot], note: str) -> None:
            key = (name, i, direction)
            if key in seen:
                return
            broke = c < boundary - buf if direction == "SHORT" else c > boundary + buf
            if not broke:
                return
            entry = bars[i + 1].open
            risk = (extreme + buf - entry) if direction == "SHORT" else (entry - (extreme - buf))
            if risk <= 0:
                return
            signals.append(Signal(name, direction, i, i + 1, boundary,
                                  extreme + buf if direction == "SHORT" else extreme - buf,
                                  target_r, tuple(p.index for p in chosen), note))
            seen.add(key)

        # Reversal tops/bottoms and shoulders use alternating confirmed pivots.
        q = ps[-5:]
        if len(q) >= 3:
            a, b, d = q[-3:]
            if [a.kind, b.kind, d.kind] == ["H", "L", "H"] and d.index-a.index >= min_separation:
                if _similar(a.price, d.price, tol):
                    emit("double_top", "SHORT", b.price, max(a.price, d.price), [a,b,d], "two comparable peaks; neckline close break")
            if [a.kind, b.kind, d.kind] == ["L", "H", "L"] and d.index-a.index >= min_separation:
                if _similar(a.price, d.price, tol):
                    emit("double_bottom", "LONG", b.price, min(a.price, d.price), [a,b,d], "two comparable troughs; neckline close break")

        if len(q) >= 5:
            a,b,h,d,e = q
            if [p.kind for p in q] == ["H","L","H","L","H"]:
                if h.price > max(a.price, e.price) + tol and _similar(a.price, e.price, tol):
                    neck = min(b.price, d.price)
                    emit("head_and_shoulders", "SHORT", neck, h.price, q, "head above comparable shoulders")
                # Three peaks with comparable highs and two intervening troughs.
                if max(a.price,bars[i].high*0+0) > 0 and max(abs(a.price-h.price),abs(h.price-e.price)) <= tol:
                    emit("triple_top", "SHORT", min(b.price,d.price), max(a.price,h.price,e.price), q, "three comparable peaks")
            if [p.kind for p in q] == ["L","H","L","H","L"]:
                if h.price < min(a.price, e.price) - tol and _similar(a.price, e.price, tol):
                    neck = max(b.price, d.price)
                    emit("inverse_head_and_shoulders", "LONG", neck, h.price, q, "head below comparable shoulders")

        # Wedges: converging swing envelope, direction confirmed only by close breakout.
        w = ps[-4:]
        if len(w) == 4 and [p.kind for p in w] == ["L","H","L","H"]:
            lo_rise = w[2].price > w[0].price
            hi_fall = w[3].price < w[1].price
            if lo_rise and hi_fall:
                emit("ascending_wedge", "SHORT", _line_value(w[0],w[2],i), max(p.price for p in w), w, "converging rising wedge; lower trendline break")
            if w[2].price < w[0].price and w[3].price > w[1].price:
                emit("descending_wedge", "LONG", _line_value(w[1],w[3],i), min(p.price for p in w), w, "converging falling wedge; upper trendline break")

        # Expanding/broadening formations: rising highs and falling lows.
        if len(w) == 4 and [p.kind for p in w] == ["L","H","L","H"]:
            expanding = w[2].price < w[0].price and w[3].price > w[1].price
            if expanding:
                emit("bearish_broadening", "SHORT", _line_value(w[0],w[2],i), max(p.price for p in w), w, "expanding range; downside boundary break")
                emit("bullish_broadening", "LONG", _line_value(w[1],w[3],i), min(p.price for p in w), w, "expanding range; upside boundary break")

        # Trend reversal: close through the most recently confirmed opposing swing.
        if len(ps) >= 2:
            last_high = next((p for p in reversed(ps) if p.kind == "H"), None)
            last_low = next((p for p in reversed(ps) if p.kind == "L"), None)
            prior = ps[-6:-2]
            if last_low and c < last_low.price - buf and any(p.kind == "H" for p in prior):
                emit("trend_reversal_structure_break", "SHORT", last_low.price, last_high.price if last_high else last_low.price+atr, ps[-6:], "bearish break of confirmed swing low")
            if last_high and c > last_high.price + buf and any(p.kind == "L" for p in prior):
                emit("trend_reversal_structure_break", "LONG", last_high.price, last_low.price if last_low else last_high.price-atr, ps[-6:], "bullish break of confirmed swing high")

        # Rounding top: a broad rolling arc with a central maximum and weakening right half.
        window = bars[max(0, i-39):i+1]
        if len(window) >= 30:
            closes = [x.close for x in window]
            mid = len(closes)//2
            left_avg = sum(closes[:mid]) / mid
            right_avg = sum(closes[mid:]) / (len(closes)-mid)
            peak = max(range(len(closes)), key=lambda z: closes[z])
            if peak >= len(closes)//3 and peak <= 2*len(closes)//3 and left_avg > closes[0] and right_avg < closes[peak] and right_avg < left_avg:
                floor = min(x.low for x in window[-10:])
                emit("rounding_top", "SHORT", floor, max(x.high for x in window), ps[-6:], "rounded distribution arc; support close break")

        # Inverted cup-and-handle: rounded trough then a weak recovery/handle and support break.
        if len(window := bars[max(0, i-39):i+1]) >= 30:
            lows = [x.close for x in window]
            mid = len(lows)//2
            trough = min(range(len(lows)), key=lambda z: lows[z])
            if trough >= len(lows)//3 and trough <= 2*len(lows)//3:
                left_rim, right_rim = max(lows[:trough+1]), max(lows[trough:])
                handle = window[-8:]
                if _similar(left_rim, right_rim, tol) and len(handle) >= 6 and max(x.high for x in handle) < right_rim + tol:
                    support = min(x.low for x in window[-12:-8])
                    emit("inverted_cup_and_handle", "SHORT", support, max(x.high for x in window), ps[-6:], "rounded cup recovery and failed handle")

        # Diamond top: expanding swings followed by contracting swings; then neckline break.
        d7 = ps[-7:]
        if len(d7) == 7 and [p.kind for p in d7] == ["H","L","H","L","H","L","H"]:
            widths = [abs(d7[j+1].price-d7[j].price) for j in range(6)]
            if widths[0] < widths[2] and widths[2] > widths[4] and d7[4].price >= d7[0].price - tol:
                emit("diamond_top", "SHORT", min(d7[1].price,d7[3].price,d7[5].price), max(p.price for p in d7), d7, "expansion then contraction; neckline breakdown")

    return signals


def signal_dict(signal: Signal) -> dict:
    return asdict(signal)
