"""
통합 모멘텀 엔진
- 가격 모멘텀(Price): mom_1m/6m/12m 가중합
- 이익 모멘텀(Earnings): earn_mom (실적 YoY / 추정 증가율)
- 팩터 모멘텀(Factor): 최근 잘 먹힌 스타일(가치·우량·가격)에 대한 종목 노출도
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _cs_rank(s: pd.Series, ascending: bool = False) -> pd.Series:
    return s.rank(ascending=ascending, method="average", na_option="bottom")


def _safe_yoy(cur, prev) -> Optional[float]:
    try:
        if cur is None or prev is None:
            return None
        cur_f, prev_f = float(cur), float(prev)
        if prev_f == 0 or np.isnan(cur_f) or np.isnan(prev_f):
            return None
        return (cur_f - prev_f) / abs(prev_f) * 100.0
    except (TypeError, ValueError):
        return None


def compute_earn_mom_from_fund(fund: dict, prev: Optional[dict]) -> Optional[float]:
    """
    DART 당기/전기 재무 → 이익 모멘텀(%).
    영업이익 YoY와 순이익 YoY의 평균(한쪽만 있으면 그 값).
    """
    if not prev:
        return None
    op_yoy = _safe_yoy(fund.get("op_income"), prev.get("op_income"))
    ni_yoy = _safe_yoy(fund.get("net_income"), prev.get("net_income"))
    vals = [v for v in (op_yoy, ni_yoy) if v is not None]
    if not vals:
        return None
    return float(np.mean(vals))


def attach_factor_momentum(
    df_all: pd.DataFrame,
    lookback: int = 6,
) -> pd.DataFrame:
    """
    전체 월별 패널에 factor_mom 컬럼을 붙인다.

    방법(데이터 효율형):
    1) 매월 가치/우량/가격 스타일 점수 산출
    2) 상위 20% 종목의 평균 mom_1m ≈ 그달 스타일 수익률 대용
    3) 최근 lookback개월 평균 → 스타일 팩터모멘텀 FM_s
    4) 종목 노출(스타일 백분위) × FM_s 합 = factor_mom
    """
    out = df_all.copy()
    if out.empty or "date" not in out.columns:
        out["factor_mom"] = np.nan
        return out

    num_cols = [
        "per", "pbr", "psr", "ev_ebitda", "roe", "op_margin", "gross_margin",
        "f_score", "mom_1m", "mom_6m", "mom_12m",
    ]
    for c in num_cols:
        if c not in out.columns:
            out[c] = np.nan
        else:
            out[c] = pd.to_numeric(out[c], errors="coerce")

    months = sorted(out["date"].astype(str).unique())
    style_ret_rows = []

    for m in months:
        g = out[out["date"].astype(str) == m]
        if len(g) < 50:
            style_ret_rows.append({"date": m, "v": np.nan, "q": np.nan, "p": np.nan})
            continue

        # 스타일 점수: 낮을수록 좋은 가치는 순위 반전
        v_score = (
            _cs_rank(g["per"], True)
            + _cs_rank(g["pbr"], True)
            + _cs_rank(g["psr"], True)
            + _cs_rank(g["ev_ebitda"], True)
        )
        q_score = (
            _cs_rank(g["roe"], False)
            + _cs_rank(g["op_margin"], False)
            + _cs_rank(g["gross_margin"], False)
            + _cs_rank(g["f_score"], False)
        )
        p_score = (
            _cs_rank(g["mom_1m"], False)
            + _cs_rank(g["mom_6m"], False)
            + _cs_rank(g["mom_12m"], False)
        )

        def _top_ret(score: pd.Series) -> float:
            tmp = g.copy()
            tmp["_s"] = score.values
            tmp = tmp.dropna(subset=["mom_1m"])
            if len(tmp) < 20:
                return float("nan")
            thr = tmp["_s"].quantile(0.8)
            top = tmp[tmp["_s"] >= thr]["mom_1m"]
            return float(top.mean()) if len(top) else float("nan")

        style_ret_rows.append(
            {
                "date": m,
                "v": _top_ret(v_score),
                "q": _top_ret(q_score),
                "p": _top_ret(p_score),
            }
        )

    style_df = pd.DataFrame(style_ret_rows).set_index("date").sort_index()
    # trailing mean of style returns
    fm = style_df.rolling(lookback, min_periods=max(2, lookback // 2)).mean()

    factor_moms = []
    for m in months:
        g = out[out["date"].astype(str) == m].copy()
        if m not in fm.index or fm.loc[m].isna().all():
            g["factor_mom"] = np.nan
            factor_moms.append(g)
            continue

        fv, fq, fp = fm.loc[m, "v"], fm.loc[m, "q"], fm.loc[m, "p"]
        # 노출: 백분위(높을수록 해당 스타일)
        exp_v = 1.0 - (
            _cs_rank(g["per"], True)
            + _cs_rank(g["pbr"], True)
            + _cs_rank(g["psr"], True)
            + _cs_rank(g["ev_ebitda"], True)
        ).rank(pct=True, ascending=True)
        exp_q = (
            _cs_rank(g["roe"], False)
            + _cs_rank(g["op_margin"], False)
            + _cs_rank(g["gross_margin"], False)
            + _cs_rank(g["f_score"], False)
        ).rank(pct=True, ascending=True)
        exp_p = (
            _cs_rank(g["mom_1m"], False)
            + _cs_rank(g["mom_6m"], False)
            + _cs_rank(g["mom_12m"], False)
        ).rank(pct=True, ascending=True)

        # 음수 스타일 수익률도 유지 (약세장에서 전 스타일 음수여도 상대 우위 반영)
        wv = float(fv) if pd.notna(fv) else 0.0
        wq = float(fq) if pd.notna(fq) else 0.0
        wp = float(fp) if pd.notna(fp) else 0.0
        if wv == 0 and wq == 0 and wp == 0:
            g["factor_mom"] = np.nan
        else:
            g["factor_mom"] = (exp_v * wv + exp_q * wq + exp_p * wp)
        factor_moms.append(g)

    return pd.concat(factor_moms, ignore_index=True)


def ensure_earn_mom_column(df: pd.DataFrame) -> pd.DataFrame:
    if "earn_mom" not in df.columns:
        df = df.copy()
        df["earn_mom"] = np.nan
    return df
