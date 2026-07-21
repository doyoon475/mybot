# -*- coding: utf-8 -*-
"""
제품 #5 MVP: 실시간 시장 국면 레이더
- KOSPI 수준 / 전일 대비
- 최근 60일 고점 대비 낙폭(DD)
- 규칙 기반 심리 국면 + 팩터 배분 추천 문구
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

from liquidity_benchmark import load_kr_benchmarks


def _regime_from_dd(dd_pct: float, vol20: Optional[float] = None) -> tuple[str, str, str]:
    """
    반환: (국면라벨, 이모지, 추천문구)
    dd_pct: 고점 대비 % (음수, 예: -12.5)
    """
    abs_dd = abs(dd_pct) if dd_pct is not None else 0.0
    high_vol = vol20 is not None and vol20 >= 0.018  # 일간 표준편차 ~1.8%

    if dd_pct <= -20:
        label, emoji = "공포 국면", "😨"
        tip = (
            "변동성이 커진 하락장입니다. 모멘텀 비중을 낮추고, "
            "F-Score·FCF가 높은 우량주와 현금 비중 확대를 추천합니다."
        )
    elif dd_pct <= -10:
        label, emoji = "불안 국면", "😰"
        tip = (
            "고점 대비 조정이 진행 중입니다. 가치·우량 비중을 유지·상향하고 "
            "단기 모멘텀 과열 종목은 비중을 줄이세요."
        )
    elif dd_pct <= -5:
        label, emoji = "경계 국면", "😐"
        tip = (
            "완만한 조정 구간입니다. 유동성 필터를 유지하고 "
            "가치와 모멘텀을 균형 있게 가져가는 것을 권장합니다."
        )
    elif dd_pct >= -2 and not high_vol:
        label, emoji = "탐욕·과열 주의", "🤑"
        tip = (
            "고점 근처입니다. 추격 매수보다 우량·저변동 비중을 점검하고 "
            "차익실현·리밸런싱 규칙을 지키세요."
        )
    else:
        label, emoji = "중립 국면", "🙂"
        tip = (
            "뚜렷한 공포/과열이 아닙니다. 현재 AI·수동 매크로 비중을 유지하되 "
            "유동성·국면 변화를 주기적으로 확인하세요."
        )

    if high_vol and dd_pct > -10:
        tip = "단기 변동성이 큽니다. " + tip
    return label, emoji, tip


def compute_kospi_regime(lookback_dd: int = 60) -> dict[str, Any]:
    """
    FDR KS11 기반 국면 스냅샷.
    """
    end = datetime.now()
    start = (end - timedelta(days=max(lookback_dd * 3, 180))).strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    bdf = load_kr_benchmarks(start, end_s, sleep_sec=0.35)
    if bdf.empty or "코스피" not in bdf.columns:
        return {"ok": False, "error": "KOSPI 데이터를 불러오지 못했습니다."}

    s = pd.to_numeric(bdf["코스피"], errors="coerce").dropna()
    if len(s) < 5:
        return {"ok": False, "error": "KOSPI 시계열이 부족합니다."}

    last = float(s.iloc[-1])
    prev = float(s.iloc[-2]) if len(s) >= 2 else last
    chg = last - prev
    chg_pct = (chg / prev * 100.0) if prev else 0.0

    window = s.iloc[-lookback_dd:] if len(s) >= lookback_dd else s
    peak = float(window.max())
    dd_pct = (last / peak - 1.0) * 100.0 if peak > 0 else 0.0

    ret = s.pct_change().dropna()
    vol20 = float(ret.iloc[-20:].std()) if len(ret) >= 20 else None

    label, emoji, tip = _regime_from_dd(dd_pct, vol20)

    return {
        "ok": True,
        "asof": s.index[-1].strftime("%Y-%m-%d"),
        "kospi": last,
        "chg": chg,
        "chg_pct": chg_pct,
        "dd_pct": dd_pct,
        "dd_lookback": lookback_dd,
        "peak": peak,
        "vol20": vol20,
        "regime": label,
        "emoji": emoji,
        "advice": tip,
    }
