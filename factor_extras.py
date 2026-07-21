"""
Phase A 팩터 보강
1) vol_12m: 최근 ~252거래일 일간수익 표준편차(연율화 %)
2) per_sec / pbr_sec: 월×섹터 내 강건 z-score (중앙값/MAD)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_vol_12m(
    df_factor: pd.DataFrame,
    df_price: pd.DataFrame,
    min_days: int = 150,
    window: int = 252,
) -> pd.DataFrame:
    """
    각 팩터 월(YYYY-MM) 해당 월의 마지막 거래일 기준
    rolling(window) 일간수익률 표준편차 × √252 (%).
    표본 < min_days 이면 NULL.
    """
    out = df_factor.copy()
    out = out.drop(columns=["vol_12m"], errors="ignore")
    if df_price is None or df_price.empty or out.empty:
        out["vol_12m"] = np.nan
        return out

    px = df_price[["date", "ticker", "close"]].copy()
    px["date"] = pd.to_datetime(px["date"], errors="coerce")
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    px = px.dropna(subset=["date", "ticker", "close"]).sort_values(["ticker", "date"])
    px["ret"] = px.groupby("ticker", sort=False)["close"].pct_change()
    px["vol_12m"] = px.groupby("ticker", sort=False)["ret"].transform(
        lambda s: s.rolling(window, min_periods=min_days).std() * np.sqrt(252.0) * 100.0
    )
    px["_ym"] = px["date"].dt.strftime("%Y-%m")
    vol_m = (
        px.dropna(subset=["vol_12m"])
        .groupby(["ticker", "_ym"], as_index=False, sort=False)["vol_12m"]
        .last()
        .rename(columns={"_ym": "date"})
    )
    out = out.merge(vol_m, on=["date", "ticker"], how="left")
    return out


def _robust_z(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    if s.notna().sum() < 5:
        return pd.Series(np.nan, index=s.index)
    med = s.median()
    mad = (s - med).abs().median()
    if mad is None or not np.isfinite(mad) or mad == 0:
        std = s.std(ddof=1)
        if std is None or not np.isfinite(std) or std == 0:
            return pd.Series(np.nan, index=s.index)
        return (s - s.mean()) / std
    return (s - med) / (1.4826 * mad)


def attach_sector_relative(
    df_factor: pd.DataFrame,
    sector_col: str = "섹터",
) -> pd.DataFrame:
    """
    월×섹터 강건 z-score.
    값이 낮을수록 섹터 대비 저평가 → 가치 랭크 ascending=True.
    """
    out = df_factor.copy()
    if out.empty or sector_col not in out.columns:
        out["per_sec"] = np.nan
        out["pbr_sec"] = np.nan
        return out

    out["per"] = pd.to_numeric(out.get("per"), errors="coerce")
    out["pbr"] = pd.to_numeric(out.get("pbr"), errors="coerce")
    out.loc[out["per"] <= 0, "per"] = np.nan
    out.loc[out["pbr"] <= 0, "pbr"] = np.nan

    gkeys = [out["date"].astype(str), out[sector_col].fillna("UNKNOWN").astype(str)]
    out["per_sec"] = out.groupby(gkeys, sort=False)["per"].transform(_robust_z)
    out["pbr_sec"] = out.groupby(gkeys, sort=False)["pbr"].transform(_robust_z)
    return out


def compute_growth_stab(df: pd.DataFrame) -> pd.Series:
    """
    다년 성장 안정성 점수 (Phase B5).
    sales_g3y / op_g3y / ni_g3y 평균 − 0.25×표준편차 (높을수록 우량).
    극단치는 ±500% 윈저라이즈.
    """
    cols = [c for c in ("sales_g3y", "op_g3y", "ni_g3y") if c in df.columns]
    if not cols:
        return pd.Series(np.nan, index=df.index)
    mat = df[cols].apply(pd.to_numeric, errors="coerce").clip(-500, 500)
    mean = mat.mean(axis=1, skipna=True)
    std = mat.std(axis=1, skipna=True)
    n = mat.notna().sum(axis=1)
    out = mean.copy()
    mask = n >= 2
    out.loc[mask] = mean.loc[mask] - 0.25 * std.loc[mask].fillna(0)
    out.loc[n == 0] = np.nan
    return out
