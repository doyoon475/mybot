# -*- coding: utf-8 -*-
"""
제품 #6: 이달의 AI 퀀트 랩 리포트
- 매크로 비중 + Top10 + 시황 서술(Perplexity)
- 세부 팩터는 AI가 올린 하이라이트 2~3개만 맛보기(유료 유도)
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

REPORT_PATH = Path("data_cache/monthly_report.md")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

# (group, key) → 표시명
SUB_LABELS = {
    ("sub_value", "per"): "PER",
    ("sub_value", "pbr"): "PBR",
    ("sub_value", "psr"): "PSR",
    ("sub_value", "ev"): "EV/EBITDA",
    ("sub_value", "per_sec"): "PER 섹터상대",
    ("sub_value", "pbr_sec"): "PBR 섹터상대",
    ("sub_quality", "roe"): "ROE",
    ("sub_quality", "opm"): "OPM",
    ("sub_quality", "gpm"): "GPM",
    ("sub_quality", "fscore"): "F-Score",
    ("sub_quality", "vol"): "저변동 vol_12m",
    ("sub_quality", "accrual"): "Accrual",
    ("sub_quality", "fcf"): "FCF Yield",
    ("sub_quality", "growth"): "growth_stab",
    ("sub_quality", "div"): "배당수익률",
    ("sub_quality", "share"): "주식수 희석",
    ("sub_quality", "treasury"): "자사주 비중 변화",
    ("sub_momentum", "price"): "가격 모멘텀",
    ("sub_momentum", "earn"): "이익 모멘텀",
    ("sub_momentum", "factor"): "팩터 모멘텀",
    ("sub_momentum", "mom1"): "1개월 등락",
    ("sub_momentum", "mom6"): "6개월 등락",
    ("sub_momentum", "mom12"): "12개월 등락",
}

GROUP_KO = {
    "sub_value": "Value",
    "sub_quality": "Quality",
    "sub_momentum": "Momentum",
}


def _defaults_from_agent() -> dict[str, dict[str, int]]:
    try:
        from macro_ai_agent import (
            DEFAULT_SUB_MOMENTUM,
            DEFAULT_SUB_QUALITY,
            DEFAULT_SUB_VALUE,
        )

        return {
            "sub_value": dict(DEFAULT_SUB_VALUE),
            "sub_quality": dict(DEFAULT_SUB_QUALITY),
            "sub_momentum": dict(DEFAULT_SUB_MOMENTUM),
        }
    except Exception:
        return {
            "sub_value": {"per": 25, "pbr": 25, "psr": 15, "ev": 15, "per_sec": 10, "pbr_sec": 10},
            "sub_quality": {
                "roe": 12, "opm": 7, "gpm": 7, "fscore": 7, "vol": 10,
                "accrual": 9, "fcf": 9, "growth": 10, "div": 9, "share": 8, "treasury": 12,
            },
            "sub_momentum": {
                "price": 40, "earn": 35, "factor": 25, "mom1": 20, "mom6": 40, "mom12": 40,
            },
        }


def pick_highlight_subs(weights: dict[str, Any], n: int = 3) -> list[dict[str, Any]]:
    """기본값 대비 비중이 가장 많이 오른 세부 팩터 n개."""
    defaults = _defaults_from_agent()
    scored: list[tuple[float, str, str, int, int]] = []
    for group in ("sub_value", "sub_quality", "sub_momentum"):
        block = weights.get(group) or {}
        base = defaults.get(group) or {}
        for key, dv in base.items():
            try:
                cur = int(block.get(key, dv))
            except (TypeError, ValueError):
                cur = dv
            delta = cur - int(dv)
            scored.append((delta, group, key, cur, int(dv)))
    scored.sort(key=lambda x: (-x[0], -x[3]))
    # 상승분이 약하면 절대 비중 상위
    if not scored or scored[0][0] <= 0:
        scored.sort(key=lambda x: -x[3])
    out = []
    for delta, group, key, cur, dv in scored[:n]:
        label = SUB_LABELS.get((group, key), key)
        direction = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        out.append(
            {
                "group": GROUP_KO.get(group, group),
                "key": key,
                "label": label,
                "weight": cur,
                "default": dv,
                "delta": delta,
                "direction": direction,
            }
        )
    return out


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _call_report_narrative(
    factor_month: str,
    reason: str,
    top_names: list[str],
    highlights: list[dict[str, Any]],
) -> dict[str, str]:
    """시황·이슈·시나리오 서술. 실패 시 빈 dict."""
    api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip().strip('"').strip("'")
    if not api_key:
        return {}

    hl = ", ".join(f"{h['group']}-{h['label']}({h['weight']})" for h in highlights)
    names = ", ".join(top_names[:10]) or "(종목 미정)"
    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""당신은 KRX 퀀트 월간 리포트 작성자입니다. 오늘={today}, 팩터기준월={factor_month}.

이미 정해진 AI 매크로 근거:
{reason}

이번 달 강조 세부팩터(맛보기): {hl}
Top 후보 종목명: {names}

아래 JSON만 출력. 마크다운 금지. 사실 불확실하면 '확인 필요'라고 쓸 것. 투자권유 금지.
{{
  "one_liner": "<한국어 1~2문장 한줄 요약>",
  "korea": "<한국 시황 2~3문장>",
  "usa": "<미국 시황 2~3문장>",
  "implication": "<이번 달 팩터 배분에 대한 시사점 1문장>",
  "issues": ["<종목/섹터 이슈 1>", "<이슈 2>", "<이슈 3>"],
  "risk_down": "<하락 시나리오 1문장>",
  "risk_up": "<상승 시나리오 1문장>"
}}
"""
    try:
        resp = requests.post(
            PERPLEXITY_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("PERPLEXITY_MODEL", "sonar-pro"),
                "temperature": 0.25,
                "messages": [
                    {
                        "role": "system",
                        "content": "KRX quant monthly report writer. Valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=90,
        )
        resp.raise_for_status()
        content = (
            resp.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            or ""
        ).strip()
        parsed = _extract_json_object(content)
        if not parsed:
            return {}
        # normalize
        issues = parsed.get("issues") or []
        if isinstance(issues, str):
            issues = [issues]
        return {
            "one_liner": str(parsed.get("one_liner") or "").strip(),
            "korea": str(parsed.get("korea") or "").strip(),
            "usa": str(parsed.get("usa") or "").strip(),
            "implication": str(parsed.get("implication") or "").strip(),
            "issues": [str(x).strip() for x in issues if str(x).strip()][:4],
            "risk_down": str(parsed.get("risk_down") or "").strip(),
            "risk_up": str(parsed.get("risk_up") or "").strip(),
        }
    except Exception as e:
        print(f"[report] Perplexity 실패: {e}")
        return {}


def _fallback_narrative(reason: str) -> dict[str, str]:
    return {
        "one_liner": (reason[:180] + "…") if len(reason) > 180 else (reason or "이번 달 균형 배분을 유지합니다."),
        "korea": "한국 시황 서술은 API 응답이 없어 생략되었습니다. AI 매크로 근거를 참고하세요.",
        "usa": "미국 시황 서술은 API 응답이 없어 생략되었습니다.",
        "implication": reason.split(".")[0] + "." if reason else "세부 비중은 사이드바에서 확인하세요.",
        "issues": ["개별 종목 이슈는 공시·뉴스를 추가 확인하세요."],
        "risk_down": "위험자산 회피 시 모멘텀 종목 낙폭이 커질 수 있습니다.",
        "risk_up": "유동성·실적 서프라이즈 시 모멘텀·성장 우량이 상대적으로 유리할 수 있습니다.",
    }


def _score_comment(row: dict[str, Any]) -> str:
    parts = []
    try:
        v, q, m = float(row.get("가치점수", 0)), float(row.get("우량점수", 0)), float(row.get("모멘텀점수", 0))
    except (TypeError, ValueError):
        return "점수 패턴 확인"
    mx = max(v, q, m)
    if mx == q and q >= v and q >= m:
        parts.append("우량")
    if mx == v:
        parts.append("가치")
    if mx == m:
        parts.append("모멘텀")
    if len(parts) >= 2:
        return "+".join(parts[:2]) + " 우세"
    return (parts[0] if parts else "균형") + " 우세"


def render_report_markdown(
    weights: dict[str, Any],
    top_rows: list[dict[str, Any]],
    factor_month: str,
    db_date: str,
    narrative: Optional[dict[str, Any]] = None,
    liq_note: str = "",
) -> str:
    reason = str(weights.get("reason") or "").strip()
    highlights = pick_highlight_subs(weights, n=3)
    names = [str(r.get("종목명") or r.get("ticker") or "") for r in top_rows]
    nar = narrative or _call_report_narrative(factor_month, reason, names, highlights)
    if not nar or not nar.get("one_liner"):
        nar = _fallback_narrative(reason)

    v = int(weights.get("value", 0))
    q = int(weights.get("quality", 0))
    m = int(weights.get("momentum", 0))
    src = str(weights.get("source") or "ai")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    hl_lines = []
    for h in highlights:
        hl_lines.append(
            f"- **{h['group']} · {h['label']}** `{h['weight']}` "
            f"(기본 {h['default']} 대비 {h['direction']}{abs(h['delta'])})"
        )
    if not hl_lines:
        hl_lines = ["- (하이라이트 없음)"]

    issue_lines = [f"- {x}" for x in (nar.get("issues") or [])] or ["- (이슈 없음)"]

    table_lines = [
        "| 순위 | 종목 | 섹터 | 가치 | 우량 | 모멘텀 | 종합 | 한 줄 |",
        "|:----:|------|------|-----:|-----:|-------:|-----:|--------|",
    ]
    for i, r in enumerate(top_rows[:10], 1):
        rank = r.get("순위", i)
        name = str(r.get("종목명") or "")[:12]
        sector = str(r.get("섹터") or "-")[:10]
        def _f(k):
            try:
                return f"{float(r.get(k, 0)):.0f}"
            except (TypeError, ValueError):
                return "-"
        table_lines.append(
            f"| {rank} | {name} | {sector} | {_f('가치점수')} | {_f('우량점수')} | "
            f"{_f('모멘텀점수')} | {_f('종합점수')} | {_score_comment(r)} |"
        )

    liq_line = liq_note or "사이드바 유동성 필터 설정을 확인하세요."

    md = f"""# 이달의 퀀트 랩 리포트
**기준월:** {factor_month} · **작성:** {now} · **소스:** {src}

> 본 자료는 참고용 리서치이며 **투자 권유가 아닙니다.**

## 1. 한 줄 요약
{nar.get('one_liner') or reason}

이번 달 매크로 배분: **가치 {v} / 우량 {q} / 모멘텀 {m}**

## 2. 매크로 시황
| 구분 | 포인트 |
|------|--------|
| **한국** | {nar.get('korea') or '-'} |
| **미국** | {nar.get('usa') or '-'} |
| **시사점** | {nar.get('implication') or '-'} |

## 3. 팩터 비중 & 세부 맛보기
**매크로:** Value {v}% · Quality {q}% · Momentum {m}%

**AI 근거**  
{reason or '(근거 없음)'}

### 이번 달 하이라이트 세부 팩터 (맛보기)
{chr(10).join(hl_lines)}

🔒 **나머지 세부 비중·종목별 PER/ROE 등 원천 지표는 유료 구독(예정)에서 제공합니다.**

## 4. Top 10 종목 스냅샷
{chr(10).join(table_lines)}

## 5. 주목 이슈
{chr(10).join(issue_lines)}

## 6. 리스크 & 체크
- 유동성: {liq_line}
- 하락 시나리오: {nar.get('risk_down') or '-'}
- 상승 시나리오: {nar.get('risk_up') or '-'}

## 7. 다음 액션
1. 이번 달 포트폴리오 확정(잠금) 여부 검토  
2. 백테스트에서 코스피/코스닥 대비 곡선 확인  
3. (선택) 하이라이트 세부 슬라이더만 미세 조정  

---
*DB 갱신 {db_date} · Generated for Quant Lab*
"""
    return md


def generate_and_save_report(
    weights: dict[str, Any],
    top_rows: list[dict[str, Any]],
    factor_month: str,
    db_date: str,
    liq_note: str = "",
) -> str:
    md = render_report_markdown(
        weights, top_rows, factor_month, db_date, narrative=None, liq_note=liq_note
    )
    try:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(md, encoding="utf-8")
    except Exception as e:
        print(f"[report] 저장 실패: {e}")
    return md


def load_saved_report() -> Optional[str]:
    if REPORT_PATH.exists():
        try:
            return REPORT_PATH.read_text(encoding="utf-8")
        except Exception:
            return None
    return None
