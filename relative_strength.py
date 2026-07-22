# -*- coding: utf-8 -*-
"""
제품 #5-b: 코스피 대비 상대강도 스크리너
- RS = 종목수익률 − 코스피수익률
- 방어: 낙폭·상대수익률이 덜 나쁜 종목 (하락장 버티기)
- 공격: RS가 높은 종목 (상승 곡선)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from liquidity_benchmark import load_kr_benchmarks


def _period_return(series: pd.Series, n: int) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < n + 1:
        return None
    a, b = float(s.iloc[-(n + 1)]), float(s.iloc[-1])
    if a == 0:
        return None
    return b / a - 1.0


def _drawdown_from_high(series: pd.Series, n: int) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < max(5, n // 2):
        return None
    w = s.iloc[-n:] if len(s) >= n else s
    peak = float(w.max())
    last = float(w.iloc[-1])
    if peak <= 0:
        return None
    return last / peak - 1.0


def compute_relative_strength(
    df_price: pd.DataFrame,
    tickers: Optional[list[str]] = None,
    lookbacks: tuple[int, ...] = (20, 60),
    min_bars: int = 40,
) -> pd.DataFrame:
    """
    종목별 ret/RS/DD 계산.
    df_price: columns date, ticker, close
    """
    if df_price is None or df_price.empty:
        return pd.DataFrame()

    df = df_price.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "ticker", "close"])
    if tickers:
        tickers = [str(t) for t in tickers]
        df = df[df["ticker"].astype(str).isin(tickers)]
    if df.empty:
        return pd.DataFrame()

    max_lb = max(lookbacks)
    end = df["date"].max()
    start = end - timedelta(days=int(max_lb * 2.5) + 30)
    df = df[df["date"] >= start]

    pivot = (
        df.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
        .sort_index()
        .ffill()
    )
    # 거래 이력 부족 종목 제거
    counts = pivot.notna().sum()
    keep = counts[counts >= min_bars].index
    pivot = pivot[keep]
    if pivot.empty or len(pivot) < max_lb + 1:
        return pd.DataFrame()

    bdf = load_kr_benchmarks(
        pivot.index.min().strftime("%Y-%m-%d"),
        pivot.index.max().strftime("%Y-%m-%d"),
        sleep_sec=0.25,
    )
    if bdf.empty or "코스피" not in bdf.columns:
        return pd.DataFrame()
    kospi = (
        pd.to_numeric(bdf["코스피"], errors="coerce")
        .reindex(pivot.index)
        .ffill()
        .bfill()
    )

    rows = []
    for t in pivot.columns:
        s = pivot[t].dropna()
        if len(s) < min_bars:
            continue
        rec: dict[str, Any] = {"ticker": str(t)}
        ok = True
        for n in lookbacks:
            r = _period_return(s, n)
            kr = _period_return(kospi.loc[s.index], n) if len(kospi.loc[s.index].dropna()) >= n + 1 else None
            # align kospi on same calendar via pivot index
            if kr is None:
                ks = kospi.dropna()
                kr = _period_return(ks, n)
            if r is None or kr is None:
                ok = False
                break
            rec[f"ret_{n}d"] = r * 100.0
            rec[f"kospi_{n}d"] = kr * 100.0
            rec[f"rs_{n}d"] = (r - kr) * 100.0
        if not ok:
            continue
        dd = _drawdown_from_high(s, max_lb)
        kdd = _drawdown_from_high(kospi, max_lb)
        rec["dd_60d"] = (dd * 100.0) if dd is not None else np.nan
        rec["kospi_dd_60d"] = (kdd * 100.0) if kdd is not None else np.nan
        rs60 = rec.get("rs_60d", np.nan)
        rs20 = rec.get("rs_20d", np.nan)
        dd60 = rec.get("dd_60d", np.nan)
        kdd60 = rec.get("kospi_dd_60d", np.nan)
        # 방어: 코스피보다 덜 빠진 정도(dd_excess) + RS (하락장 버티기)
        # dd_excess > 0 → 지수보다 낙폭 작음
        if pd.notna(dd60) and pd.notna(kdd60):
            dd_excess = float(dd60) - float(kdd60)
        else:
            dd_excess = -999.0
        rec["dd_vs_kospi"] = dd_excess if dd_excess != -999.0 else np.nan
        rec["defensive_score"] = (
            (0.50 * dd_excess)
            + (0.35 * (rs60 if pd.notna(rs60) else -999))
            + (0.15 * (rs20 if pd.notna(rs20) else -999))
        )
        # 공격: 단기·중기 RS (상승 곡선)
        rec["offensive_score"] = (
            (0.45 * (rs20 if pd.notna(rs20) else -999))
            + (0.55 * (rs60 if pd.notna(rs60) else -999))
        )
        rows.append(rec)

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out["asof"] = pivot.index.max().strftime("%Y-%m-%d")
    return out


def top_defensive(df_rs: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    if df_rs is None or df_rs.empty:
        return pd.DataFrame()
    return df_rs.sort_values("defensive_score", ascending=False).head(n).reset_index(drop=True)


def top_offensive(df_rs: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    if df_rs is None or df_rs.empty:
        return pd.DataFrame()
    return df_rs.sort_values("offensive_score", ascending=False).head(n).reset_index(drop=True)
