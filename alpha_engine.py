"""
alpha_engine.py
고급 복합 모멘텀 알파 엔진
- 실적 모멘텀(Earnings Momentum): FCF / 법인세비용차감전순이익 YoY
- 가치 모멘텀(Value Momentum): PER / PBR 분기 변화율
- 회계·세무 Placeholder: 이연법인세 부채 증감 등 추후 가감 가능
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# 필수 입력 컬럼 가이드 (DART + 주가 병합 DF 기준)
REQUIRED_COLS = {
    "ticker",
    "date",  # 분기/월 기준일 (datetime 또는 YYYY-MM / YYYY-Qn)
    "controlling_ni",  # 지배주주 당기순이익
    "ocf",  # 영업활동현금흐름
    "capex",  # 유형자산 취득 등 자본적지출 (없으면 0 처리)
    "ebt",  # 법인세비용차감전순이익
    "equity",  # 자본총계 (지배주주지분 권장)
    "per",
    "pbr",
}


def _safe_yoy(curr: pd.Series, prev: pd.Series) -> pd.Series:
    """전년 동기 대비 성장률. 분모 0/NaN은 NaN으로 반환."""
    prev_safe = prev.replace(0, np.nan)
    return (curr - prev) / prev_safe.abs()


def _safe_pct_change(curr: pd.Series, prev: pd.Series) -> pd.Series:
    """최근 1분기 변화율. 분모 0/NaN은 NaN."""
    prev_safe = prev.replace(0, np.nan)
    return (curr - prev) / prev_safe.abs()


def _minmax_0_100(s: pd.Series) -> pd.Series:
    """크로스섹션 정규화 → 0~100점. 전부 동일/NaN이면 50점."""
    s = pd.to_numeric(s, errors="coerce")
    lo, hi = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(lo) or pd.isna(hi) or hi == lo:
        return pd.Series(50.0, index=s.index)
    return ((s - lo) / (hi - lo) * 100.0).clip(0, 100)


def calculate_advanced_momentum(df: pd.DataFrame) -> pd.DataFrame:
    """
    DART 재무 + 주가 병합 DataFrame → 복합 모멘텀 스코어(0~100) 산출.

    Parameters
    ----------
    df : DataFrame
        ticker, date 및 재무/밸류에이션 컬럼 포함.
        동일 ticker에 대해 시계열이 최소 5분기(YoY+직전분기) 권장.

    Returns
    -------
    DataFrame
        원본 컬럼 + earnings_mom, value_mom, tax_adjust_placeholder,
        composite_momentum_raw, composite_momentum_score
    """
    out = df.copy()

    # ---- 타입/결측 방어 ----
    if "date" not in out.columns or "ticker" not in out.columns:
        raise ValueError("df에는 최소한 'ticker', 'date' 컬럼이 필요합니다.")

    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date", "ticker"]).sort_values(["ticker", "date"])

    numeric_cols = [
        "controlling_ni",
        "ocf",
        "capex",
        "ebt",
        "equity",
        "per",
        "pbr",
        # --- 회계·세무 Placeholder 컬럼 (없으면 0으로 채움) ---
        "deferred_tax_liability",  # 이연법인세부채
        "deferred_tax_asset",  # 이연법인세자산
        "tax_adjustment",  # 세무조정 항목(가산/차감) 금액
    ]
    for c in numeric_cols:
        if c not in out.columns:
            out[c] = 0.0
        out[c] = pd.to_numeric(out[c], errors="coerce")

    g = out.groupby("ticker", sort=False)

    # =========================================================
    # 1) 실적 모멘텀 (Earnings Momentum)
    #    진성 FCF ≈ OCF - CapEx
    #    YoY: 동일 분기 전년 대비 (shift 4, 분기 데이터 가정)
    # =========================================================
    out["fcf"] = out["ocf"] - out["capex"].fillna(0)

    fcf_yoy = _safe_yoy(out["fcf"], g["fcf"].shift(4))
    ebt_yoy = _safe_yoy(out["ebt"], g["ebt"].shift(4))

    # 두 성장률 평균 (한쪽만 유효하면 유효값만 사용)
    out["earnings_mom"] = pd.concat([fcf_yoy, ebt_yoy], axis=1).mean(axis=1, skipna=True)

    # =========================================================
    # 2) 가치 모멘텀 (Value Momentum)
    #    PER/PBR이 낮아질수록(저평가 진입 속도↑) 가점
    #    → 변화율에 -1을 곱해 "하락 = 양의 모멘텀"
    # =========================================================
    per_chg = _safe_pct_change(out["per"], g["per"].shift(1))
    pbr_chg = _safe_pct_change(out["pbr"], g["pbr"].shift(1))
    out["value_mom"] = (-per_chg + -pbr_chg) / 2.0

    # =========================================================
    # 3) 회계·세무 Placeholder (추후 팩터 가감용)
    #    - 이연법인세부채 증감: 증가 시 보수적으로 스코어 차감 가능
    #    - 이연법인세자산 증감: 회수가능성 검토 후 가점 가능
    #    - tax_adjustment: 비정상 세무조정 스케일 반영
    #    현재는 뼈대만 두고 composite에 0 가중치로 연결.
    # =========================================================
    dtl_chg = out["deferred_tax_liability"] - g["deferred_tax_liability"].shift(1)
    dta_chg = out["deferred_tax_asset"] - g["deferred_tax_asset"].shift(1)

    # equity 대비 비율로 스케일 (분모 0 방어)
    equity_abs = out["equity"].replace(0, np.nan).abs()
    out["dtl_chg_ratio"] = dtl_chg / equity_abs
    out["dta_chg_ratio"] = dta_chg / equity_abs
    out["tax_adj_ratio"] = out["tax_adjustment"] / equity_abs

    # Placeholder 스코어: 부채 증감은 감점(-), 자산 증감은 가점(+) 방향의 주석만 유지
    # W_TAX를 0→양수로 올리면 즉시 복합 스코어에 반영됨.
    W_TAX = 0.0  # TODO: CTA/세무 딥다이브 검증 후 0.05~0.15 권장
    out["tax_adjust_placeholder"] = (
        (-out["dtl_chg_ratio"].fillna(0)) * 0.5
        + (out["dta_chg_ratio"].fillna(0)) * 0.3
        + (-out["tax_adj_ratio"].fillna(0).abs()) * 0.2
    )

    # =========================================================
    # 4) 복합 모멘텀 → 일자별 크로스섹션 0~100 랭킹 스코어
    # =========================================================
    W_EARNINGS = 0.55
    W_VALUE = 0.45

    out["composite_momentum_raw"] = (
        out["earnings_mom"].fillna(0) * W_EARNINGS
        + out["value_mom"].fillna(0) * W_VALUE
        + out["tax_adjust_placeholder"].fillna(0) * W_TAX
    )

    out["composite_momentum_score"] = (
        out.groupby("date", sort=False)["composite_momentum_raw"]
        .transform(_minmax_0_100)
        .fillna(50.0)
    )

    return out


if __name__ == "__main__":
    # 최소 동작 스모크 테스트 (가짜 분기 패널)
    demo = pd.DataFrame(
        {
            "ticker": ["005930"] * 5 + ["000660"] * 5,
            "date": pd.to_datetime(
                [
                    "2024-03-31",
                    "2024-06-30",
                    "2024-09-30",
                    "2024-12-31",
                    "2025-03-31",
                ]
                * 2
            ),
            "controlling_ni": [1e12, 1.1e12, 1.2e12, 1.0e12, 1.3e12] * 2,
            "ocf": [1.5e12, 1.6e12, 1.7e12, 1.4e12, 1.8e12] * 2,
            "capex": [0.4e12, 0.5e12, 0.45e12, 0.5e12, 0.55e12] * 2,
            "ebt": [1.2e12, 1.3e12, 1.4e12, 1.1e12, 1.5e12] * 2,
            "equity": [3e14, 3.1e14, 3.2e14, 3.15e14, 3.3e14] * 2,
            "per": [15.0, 14.5, 13.0, 12.5, 11.0, 20.0, 19.0, 18.0, 17.0, 16.0],
            "pbr": [1.5, 1.4, 1.3, 1.25, 1.1, 2.0, 1.9, 1.8, 1.7, 1.6],
            "deferred_tax_liability": [1e10, 1.1e10, 1.05e10, 1.2e10, 1.15e10] * 2,
            "deferred_tax_asset": [5e9, 5.2e9, 5.1e9, 5.5e9, 5.4e9] * 2,
            "tax_adjustment": [0, 0, 0, 0, 0] * 2,
        }
    )
    result = calculate_advanced_momentum(demo)
    cols = [
        "ticker",
        "date",
        "earnings_mom",
        "value_mom",
        "tax_adjust_placeholder",
        "composite_momentum_score",
    ]
    print(result[cols].tail(4).to_string(index=False))
