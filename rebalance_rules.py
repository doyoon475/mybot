# -*- coding: utf-8 -*-
"""
투자 룰 · 리밸런싱 주기 (버퍼 / 비중 캡 / 월·분기·반기 + 회전율·최소보유·ADV).

대시보드 UI와 백테스트가 동일 파라미터를 쓰도록 한곳에 모은다.
DB writer와 무관 (순수 로직).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

# 프리셋: (진입 상위 N = 매수 목표, 유지 상한 M, 설명)
BUFFER_PRESETS: Dict[str, Tuple[int, int, str]] = {
    "표준 버퍼 (1-10 매수 / 11-20 유지)": (
        10,
        20,
        "전형적인 버퍼. 10위 밖이어도 20위까지는 유지해 잦은 교체를 줄입니다.",
    ),
    "타이트 (1-10 매수 / 11-15 유지)": (
        10,
        15,
        "버퍼가 좁아 순위에 더 민감. 회전율↑ · 시그널 반응↑.",
    ),
    "넓은 버퍼 (1-20 매수 / 21-40 유지)": (
        20,
        40,
        "스마트베타형 넓은 퇴출 버퍼. 회전율↓ · 집중도↓.",
    ),
    "집중 10종목 (버퍼 없음)": (
        10,
        10,
        "상위 10만 보유. 11위부터 매도 — 이론 포트에 가깝고 회전율↑.",
    ),
    "커스텀": (10, 20, "아래에서 진입·유지 순위를 직접 지정합니다."),
}

REBALANCE_FREQ: Dict[str, Tuple[int, str]] = {
    "월간 (매월)": (
        1,
        "시그널 반응이 가장 빠르고 CAGR가 높게 나오기 쉽지만, 수수료·슬리피지·MDD 부담이 큽니다. "
        "단기 모멘텀에 자주 쓰입니다.",
    ),
    "분기 (3개월: 1·4·7·10월)": (
        3,
        "수익·위험·거래비용의 실무 균형점으로 가장 많이 쓰입니다. "
        "수수료 반영 시 월간보다 샤프가 나아지는 경우가 많습니다.",
    ),
    "반기 (6개월: 1·7월)": (
        6,
        "회전율↓·운용 부담↓. 가치·퀄리티·대형주처럼 시그널이 완만한 전략에 잘 맞습니다. "
        "시장 변화 대응은 분기보다 느립니다.",
    ),
}


@dataclass(frozen=True)
class TradeRules:
    buy_n: int = 10
    hold_n: int = 20
    stock_cap: float = 0.15  # 0이면 캡 미적용
    target_equal_weight: bool = True
    rebalance_months: int = 1  # 1|3|6
    sell_preview_to: int = 50
    # --- 기관식 확장 (선택) ---
    turnover_cap: float = 0.0  # 0=off, 예: 0.20 = 1회 리밸런싱 명목 교체 ≤ 자산의 20%
    min_hold_cycles: int = 0  # 0=off, 매수 후 N회 리밸런싱 주기 동안 강제 유지
    adv_max_pct: float = 0.0  # 0=off, 매수 ≤ 20일 평균 거래대금의 x%
    sector_cap: float = 0.0  # 0=off, 단일 섹터 비중 상한
    mdd_halt_pct: float = 0.0  # 0=off, 고점 대비 낙폭(%) 이상이면 신규 매수 중단
    max_positions: int = 0  # 0=off, 보유 종목 수 상한(신규 편입만 차단)

    def __post_init__(self):
        object.__setattr__(self, "buy_n", max(1, int(self.buy_n)))
        object.__setattr__(self, "hold_n", max(self.buy_n, int(self.hold_n)))
        object.__setattr__(
            self, "stock_cap", max(0.0, float(self.stock_cap or 0.0))
        )
        object.__setattr__(
            self, "rebalance_months", int(self.rebalance_months or 1)
        )
        object.__setattr__(
            self, "turnover_cap", max(0.0, min(1.0, float(self.turnover_cap or 0.0)))
        )
        object.__setattr__(
            self, "min_hold_cycles", max(0, int(self.min_hold_cycles or 0))
        )
        object.__setattr__(
            self, "adv_max_pct", max(0.0, min(0.2, float(self.adv_max_pct or 0.0)))
        )
        object.__setattr__(
            self, "sector_cap", max(0.0, min(1.0, float(self.sector_cap or 0.0)))
        )
        object.__setattr__(
            self, "mdd_halt_pct", max(0.0, min(80.0, float(self.mdd_halt_pct or 0.0)))
        )
        object.__setattr__(
            self, "max_positions", max(0, int(self.max_positions or 0))
        )

    @property
    def target_weight(self) -> float:
        if self.target_equal_weight and self.buy_n > 0:
            return 1.0 / self.buy_n
        return 0.10

    def summary(self) -> str:
        cap = (
            f"종목캡 {self.stock_cap*100:.0f}%"
            if self.stock_cap > 0
            else "종목캡 없음"
        )
        freq = {1: "월간", 3: "분기", 6: "반기"}.get(
            self.rebalance_months, f"{self.rebalance_months}개월"
        )
        extras = []
        if self.turnover_cap > 0:
            extras.append(f"회전율≤{self.turnover_cap*100:.0f}%")
        if self.min_hold_cycles > 0:
            extras.append(f"최소보유{self.min_hold_cycles}주기")
        if self.adv_max_pct > 0:
            extras.append(f"ADV≤{self.adv_max_pct*100:.1f}%")
        if self.sector_cap > 0:
            extras.append(f"섹터캡{self.sector_cap*100:.0f}%")
        if self.mdd_halt_pct > 0:
            extras.append(f"MDD중단{self.mdd_halt_pct:.0f}%")
        if self.max_positions > 0:
            extras.append(f"최대보유{self.max_positions}")
        extra = (" · " + " · ".join(extras)) if extras else ""
        return (
            f"1-{self.buy_n}위 매수 / {self.buy_n+1}-{self.hold_n}위 유지 / "
            f"{self.hold_n+1}위 밖 매도 · {cap} · 리밸런싱 {freq}{extra}"
        )


def resolve_buffer_preset(preset_label: str, buy_n: int, hold_n: int) -> Tuple[int, int]:
    if preset_label in BUFFER_PRESETS and preset_label != "커스텀":
        b, h, _ = BUFFER_PRESETS[preset_label]
        return b, h
    return max(1, int(buy_n)), max(int(buy_n), int(hold_n))


def is_calendar_rebalance_month(ym: str, freq_months: int) -> bool:
    """달력 기준 리밸런싱 월 여부 (YYYY-MM)."""
    m = int(str(ym)[5:7])
    f = int(freq_months or 1)
    if f <= 1:
        return True
    if f == 3:
        return m in (1, 4, 7, 10)
    if f == 6:
        return m in (1, 7)
    return ((m - 1) % f) == 0


def buckets_from_ranks(
    tickers_by_rank: Sequence[str],
    rules: TradeRules,
) -> Tuple[List[str], List[str], List[str]]:
    ranked = [str(t) for t in tickers_by_rank]
    buy = ranked[: rules.buy_n]
    hold = ranked[rules.buy_n : rules.hold_n]
    sell = ranked[rules.hold_n : rules.sell_preview_to]
    return buy, hold, sell


def assign_actions_by_rules(
    df_ranked: pd.DataFrame,
    rules: TradeRules,
    rank_col: str = "순위",
) -> pd.DataFrame:
    out = df_ranked.copy()
    if rank_col not in out.columns:
        out.insert(0, rank_col, np.arange(1, len(out) + 1))
    out["액션"] = "관망"
    r = out[rank_col]
    out.loc[r <= rules.buy_n, "액션"] = "매수"
    out.loc[(r > rules.buy_n) & (r <= rules.hold_n), "액션"] = "유지"
    out.loc[
        (r > rules.hold_n) & (r <= rules.sell_preview_to), "액션"
    ] = "매도"
    return out


def apply_min_hold_to_sells(
    to_sell: Set[str],
    entry_cycle: Dict[str, int],
    current_cycle: int,
    min_hold_cycles: int,
) -> Tuple[Set[str], Set[str]]:
    """
    최소 보유 미달 종목은 매도 보류 → protected 집합으로 반환.
    """
    if min_hold_cycles <= 0:
        return to_sell, set()
    protected = set()
    allowed = set()
    for t in to_sell:
        entered = entry_cycle.get(t)
        if entered is None:
            allowed.add(t)
            continue
        if (current_cycle - entered) < min_hold_cycles:
            protected.add(t)
        else:
            allowed.add(t)
    return allowed, protected


def filter_buys_by_max_positions(
    buy_list: Sequence[str],
    portfolio: Dict[str, float],
    max_positions: int,
) -> List[str]:
    """
    최대 보유 종목 수: 이미 보유 종목은 통과, 신규는 남은 슬롯만큼만 허용.
    max_positions<=0 이면 제한 없음. 강제 매도는 하지 않음.
    """
    if max_positions <= 0:
        return list(buy_list)
    held = {str(t) for t in portfolio.keys()}
    free = max(0, int(max_positions) - len(held))
    out: List[str] = []
    new_used = 0
    for t in buy_list:
        ts = str(t)
        if ts in held:
            out.append(t)
            continue
        if new_used < free:
            out.append(t)
            new_used += 1
            held.add(ts)  # 같은 리밸런싱에서 슬롯 이중 사용 방지
    return out


def filter_buys_by_sector_cap(
    buy_list: Sequence[str],
    portfolio: Dict[str, float],
    prices: pd.Series,
    total_asset: float,
    sector_of: Dict[str, str],
    sector_cap: float,
    target_weight: float,
) -> List[str]:
    """목표 매수 후 섹터 비중이 캡을 넘을 종목은 매수 목록에서 후순위로 미룸(제외)."""
    if sector_cap <= 0 or total_asset <= 0:
        return list(buy_list)
    # 현재 섹터 비중
    sec_val: Dict[str, float] = {}
    for t, sh in portfolio.items():
        px = float(prices.get(t, 0) or 0)
        if px <= 0:
            continue
        sec = sector_of.get(str(t), "기타")
        sec_val[sec] = sec_val.get(sec, 0.0) + sh * px

    out = []
    for t in buy_list:
        sec = sector_of.get(str(t), "기타")
        projected = sec_val.get(sec, 0.0) + target_weight * total_asset
        if projected / total_asset <= sector_cap + 1e-9:
            out.append(t)
            sec_val[sec] = projected
        # 캡 초과 시 스킵 (다음 리밸런싱까지 미편입)
    return out


def max_buy_value_by_adv(
    ticker: str,
    avg_tv: Dict[str, float],
    adv_max_pct: float,
) -> Optional[float]:
    """
    ADV 한도 매수 가능 금액(원).
    None → 제한 없음(ADV 미적용 또는 데이터 없음).
    데이터가 없는데 0을 반환하면 매수가 전면 차단되어 적립금만 쌓이는
    직선 자산 곡선이 되므로, 결측은 '제한 없음'으로 둔다.
    """
    if adv_max_pct <= 0:
        return None
    tv = float(avg_tv.get(str(ticker), 0) or 0)
    if tv <= 0:
        return None
    return tv * adv_max_pct


def clip_trades_by_turnover(
    sell_values: Dict[str, float],
    buy_budgets: Dict[str, float],
    total_asset: float,
    turnover_cap: float,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    편도 기준이 아닌 매도+매수 명목합 / 자산 ≤ turnover_cap 이 되도록 축소.
    매도·매수를 비례 축소.
    """
    if turnover_cap <= 0 or total_asset <= 0:
        return sell_values, buy_budgets
    sell_sum = sum(max(0.0, v) for v in sell_values.values())
    buy_sum = sum(max(0.0, v) for v in buy_budgets.values())
    gross = sell_sum + buy_sum
    limit = turnover_cap * total_asset
    if gross <= limit or gross <= 0:
        return sell_values, buy_budgets
    scale = limit / gross
    return (
        {t: v * scale for t, v in sell_values.items()},
        {t: v * scale for t, v in buy_budgets.items()},
    )
