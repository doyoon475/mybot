# -*- coding: utf-8 -*-
"""유동성 필터 · 벤치마크 지수 로더 (제품 로드맵 #1, #11)."""
from __future__ import annotations

import time
from typing import Optional, Set

import pandas as pd


def avg_trading_value(
    df_price: pd.DataFrame,
    asof: Optional[pd.Timestamp] = None,
    lookback: int = 20,
) -> pd.Series:
    """
    종목별 최근 lookback 거래일 평균 거래대금(원) = mean(close * volume).
    index = ticker (A######)
    """
    if df_price is None or df_price.empty:
        return pd.Series(dtype=float)
    need = {"date", "ticker", "close"}
    if not need.issubset(df_price.columns):
        return pd.Series(dtype=float)
    df = df_price.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "volume" not in df.columns:
        return pd.Series(dtype=float)
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    if asof is not None:
        asof = pd.Timestamp(asof)
        df = df[df["date"] <= asof]
    df = df.dropna(subset=["close", "volume"])
    if df.empty:
        return pd.Series(dtype=float)
    df["tv"] = df["close"] * df["volume"]
    # 종목별 최근 lookback일
    df = df.sort_values(["ticker", "date"])
    tail = df.groupby("ticker", sort=False).tail(lookback)
    return tail.groupby("ticker")["tv"].mean()


def liquid_tickers(
    df_price: pd.DataFrame,
    min_avg_tv_won: float,
    asof: Optional[pd.Timestamp] = None,
    lookback: int = 20,
) -> Set[str]:
    """평균 거래대금 >= min_avg_tv_won 인 티커 집합."""
    s = avg_trading_value(df_price, asof=asof, lookback=lookback)
    if s.empty:
        return set()
    return set(s[s >= min_avg_tv_won].index.astype(str))


def load_kr_benchmarks(
    start: str,
    end: Optional[str] = None,
    sleep_sec: float = 0.4,
) -> pd.DataFrame:
    """
    FDR 코스피(KS11) / 코스닥(KQ11) 일별 종가.
    반환: DatetimeIndex, columns=['코스피','코스닥']
    """
    import FinanceDataReader as fdr

    frames = []
    for code, col in (("KS11", "코스피"), ("KQ11", "코스닥")):
        try:
            df = fdr.DataReader(code, start, end)
            time.sleep(sleep_sec)
            if df is None or df.empty:
                continue
            close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
            s = pd.to_numeric(close, errors="coerce").rename(col)
            s.index = pd.to_datetime(s.index)
            frames.append(s)
        except Exception as e:
            print(f"[warn] benchmark {code}: {e}")
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1).sort_index()
    return out.dropna(how="all")
