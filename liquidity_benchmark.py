# -*- coding: utf-8 -*-
"""유동성 필터 · 벤치마크 지수 로더 (제품 로드맵 #1, #11).

실무 권고(절대 거래대금 + 하위% 절사 + 시총 하위 제외)를 조합할 수 있다.
DB는 읽기만 하며 accrual/FCF 등 writer와 충돌하지 않는다.
"""
from __future__ import annotations

import sqlite3
import time
from typing import Dict, Optional, Set

import pandas as pd


def avg_trading_value(
    df_price: pd.DataFrame,
    asof: Optional[pd.Timestamp] = None,
    lookback: int = 20,
    tickers: Optional[Set[str]] = None,
) -> pd.Series:
    """
    종목별 최근 lookback 거래일 평균 거래대금(원) = mean(close * volume).
    index = ticker (A######)

    tickers가 있으면 해당 종목만 계산(백테스트 ADV 가속).
    """
    if df_price is None or df_price.empty:
        return pd.Series(dtype=float)
    need = {"date", "ticker", "close"}
    if not need.issubset(df_price.columns):
        return pd.Series(dtype=float)

    # 불필요한 전체 copy 최소화: 필터 후 필요한 컬럼만
    cols = ["date", "ticker", "close"]
    if "volume" not in df_price.columns:
        return pd.Series(dtype=float)
    cols.append("volume")

    df = df_price
    if tickers is not None:
        tk = {str(t) for t in tickers}
        df = df[df["ticker"].astype(str).isin(tk)]
    if asof is not None:
        asof = pd.Timestamp(asof)
        dcol = df["date"]
        if not pd.api.types.is_datetime64_any_dtype(dcol):
            dcol = pd.to_datetime(dcol)
            df = df.assign(date=dcol)
        df = df[df["date"] <= asof]
    if df.empty:
        return pd.Series(dtype=float)

    close = pd.to_numeric(df["close"], errors="coerce")
    vol = pd.to_numeric(df["volume"], errors="coerce")
    work = pd.DataFrame(
        {
            "ticker": df["ticker"].astype(str),
            "date": pd.to_datetime(df["date"])
            if not pd.api.types.is_datetime64_any_dtype(df["date"])
            else df["date"],
            "tv": close * vol,
        }
    ).dropna(subset=["tv"])
    if work.empty:
        return pd.Series(dtype=float)
    work = work.sort_values(["ticker", "date"])
    tail = work.groupby("ticker", sort=False).tail(lookback)
    return tail.groupby("ticker")["tv"].mean()


def liquid_tickers(
    df_price: pd.DataFrame,
    min_avg_tv_won: float,
    asof: Optional[pd.Timestamp] = None,
    lookback: int = 20,
) -> Set[str]:
    """평균 거래대금 >= min_avg_tv_won 인 티커 집합 (하위 호환)."""
    return filter_liquid_universe(
        df_price,
        min_avg_tv_won=min_avg_tv_won,
        asof=asof,
        lookback=lookback,
    )


def filter_liquid_universe(
    df_price: pd.DataFrame,
    *,
    min_avg_tv_won: float = 0.0,
    tv_bottom_pct: float = 0.0,
    marcap_by_ticker: Optional[Dict[str, float]] = None,
    marcap_bottom_pct: float = 0.0,
    asof: Optional[pd.Timestamp] = None,
    lookback: int = 20,
    universe: Optional[Set[str]] = None,
) -> Set[str]:
    """
    유동성 유니버스 필터 (AND 결합).

    - min_avg_tv_won: 20일 평균 거래대금 절대 하한 (원). 0이면 미적용.
    - tv_bottom_pct: 거래대금 하위 비율 절사 (0.0~0.5). 예: 0.2 = 하위 20% 제외.
    - marcap_by_ticker + marcap_bottom_pct: 시총 하위 비율 제외.
    - universe: 후보 집합이 있으면 그 안에서만 평가.
    """
    # 하위% 절사는 후보 유니버스 안에서 상대 비교 → 유니버스만 계산해도 됨
    tv = avg_trading_value(
        df_price, asof=asof, lookback=lookback, tickers=universe
    )
    if tv.empty:
        return set()

    if universe is not None:
        tv = tv[tv.index.astype(str).isin(universe)]
        if tv.empty:
            return set()

    ok = tv.index.astype(str)
    mask = pd.Series(True, index=tv.index)

    if min_avg_tv_won and min_avg_tv_won > 0:
        mask &= tv >= float(min_avg_tv_won)

    pct = float(tv_bottom_pct or 0.0)
    if pct > 0:
        pct = min(max(pct, 0.0), 0.5)
        thr = tv.quantile(pct)
        mask &= tv >= thr

    m_pct = float(marcap_bottom_pct or 0.0)
    if m_pct > 0 and marcap_by_ticker:
        m_pct = min(max(m_pct, 0.0), 0.5)
        caps = pd.Series(
            {
                str(t): float(marcap_by_ticker[t])
                for t in ok
                if t in marcap_by_ticker
                and marcap_by_ticker[t] is not None
                and marcap_by_ticker[t] > 0
            }
        )
        if not caps.empty:
            m_thr = caps.quantile(m_pct)
            # 시총 모르는 종목은 보수적으로 탈락(테마 동전주 방어)
            pass_m = set(caps[caps >= m_thr].index.astype(str))
            mask &= pd.Series(mask.index.astype(str).isin(pass_m), index=mask.index)

    return set(mask[mask].index.astype(str))


def load_marcap_map(
    db_path: Optional[str] = None,
    asof_month: Optional[str] = None,
    use_fdr_fallback: bool = True,
) -> Dict[str, float]:
    """
    시총(원) 맵. 우선 monthly_shares(PIT), 없으면 FDR 현재 상장 시총.
    DB는 SELECT만 수행.
    """
    out: Dict[str, float] = {}
    path = db_path
    if path:
        try:
            conn = sqlite3.connect(path, timeout=30)
            tabs = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "monthly_shares" in tabs:
                if asof_month:
                    rows = conn.execute(
                        """
                        SELECT ticker, marcap FROM monthly_shares
                        WHERE date=? AND marcap IS NOT NULL AND marcap > 0
                        """,
                        (asof_month[:7],),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT ticker, marcap FROM monthly_shares
                        WHERE date = (SELECT MAX(date) FROM monthly_shares)
                          AND marcap IS NOT NULL AND marcap > 0
                        """
                    ).fetchall()
                for t, m in rows:
                    out[str(t)] = float(m)
            conn.close()
        except Exception:
            pass

    if out or not use_fdr_fallback:
        return out

    try:
        from factor_builder import load_listings_marcap

        listing = load_listings_marcap()
        if listing is not None and not listing.empty and "marcap" in listing.columns:
            for t, m in listing.set_index("ticker")["marcap"].items():
                try:
                    mv = float(m)
                except (TypeError, ValueError):
                    continue
                if mv > 0:
                    out[str(t)] = mv
    except Exception:
        pass
    return out


def describe_liq_filter(
    *,
    min_tv_eok: float,
    tv_bottom_pct: float = 0.0,
    marcap_bottom_pct: float = 0.0,
    marcap_source: str = "",
) -> str:
    parts = [f"20일 평균 거래대금 ≥ {min_tv_eok:g}억"]
    if tv_bottom_pct and tv_bottom_pct > 0:
        parts.append(f"거래대금 하위 {tv_bottom_pct*100:.0f}% 제외")
    if marcap_bottom_pct and marcap_bottom_pct > 0:
        src = f" ({marcap_source})" if marcap_source else ""
        parts.append(f"시총 하위 {marcap_bottom_pct*100:.0f}% 제외{src}")
    return " · ".join(parts)


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
