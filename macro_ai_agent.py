"""
매크로·세부 팩터 비중 AI 에이전트
Perplexity로 가치/우량/모멘텀 매크로 + 각 세부 비중 + 근거 문장을 산출합니다.
결과는 data_cache/ai_macro_weights.json 에 저장됩니다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

CACHE_PATH = Path("data_cache/ai_macro_weights.json")
PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"

DEFAULT_SUB_VALUE = {"per": 30, "pbr": 30, "psr": 20, "ev": 20}
DEFAULT_SUB_QUALITY = {"roe": 40, "opm": 20, "gpm": 20, "fscore": 20}
DEFAULT_SUB_MOMENTUM = {
    "price": 40,
    "earn": 35,
    "factor": 25,
    "mom1": 20,
    "mom6": 40,
    "mom12": 40,
}

DEFAULT_WEIGHTS = {
    "value": 34,
    "quality": 33,
    "momentum": 33,
    "sub_value": dict(DEFAULT_SUB_VALUE),
    "sub_quality": dict(DEFAULT_SUB_QUALITY),
    "sub_momentum": dict(DEFAULT_SUB_MOMENTUM),
    "reason": "기본 균형 배분(가치/우량/모멘텀 + 세부 균등 근사).",
}


def _norm_group(d: Any, defaults: dict[str, int]) -> dict[str, int]:
    src = d if isinstance(d, dict) else {}
    out: dict[str, int] = {}
    for k, dv in defaults.items():
        try:
            out[k] = max(0, int(round(float(src.get(k, dv)))))
        except (TypeError, ValueError):
            out[k] = dv
    total = sum(out.values())
    if total <= 0:
        return dict(defaults)
    keys = list(out.keys())
    scaled = {k: int(round(out[k] * 100 / total)) for k in keys}
    # 합 100 보정
    drift = 100 - sum(scaled.values())
    scaled[keys[0]] = max(0, scaled[keys[0]] + drift)
    return scaled


def _normalize_weights(data: dict[str, Any]) -> dict[str, Any]:
    try:
        v = int(round(float(data.get("value", 34))))
        q = int(round(float(data.get("quality", 33))))
        m = int(round(float(data.get("momentum", 33))))
    except (TypeError, ValueError):
        base = dict(DEFAULT_WEIGHTS)
        base["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base["source"] = "fallback"
        return base

    total = v + q + m
    if total <= 0:
        base = dict(DEFAULT_WEIGHTS)
        base["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base["source"] = "fallback"
        return base

    v = int(round(v * 100 / total))
    q = int(round(q * 100 / total))
    m = 100 - v - q

    # nested under "sub" or flat keys
    sub = data.get("sub") if isinstance(data.get("sub"), dict) else {}
    sub_value = data.get("sub_value") or sub.get("value") or DEFAULT_SUB_VALUE
    sub_quality = data.get("sub_quality") or sub.get("quality") or DEFAULT_SUB_QUALITY
    sub_momentum = data.get("sub_momentum") or sub.get("momentum") or DEFAULT_SUB_MOMENTUM

    # momentum: price/earn/factor 그룹과 mom1/6/12 각각 정규화
    sm_in = dict(sub_momentum) if isinstance(sub_momentum, dict) else {}
    pillar = _norm_group(
        {k: sm_in.get(k, DEFAULT_SUB_MOMENTUM[k]) for k in ("price", "earn", "factor")},
        {k: DEFAULT_SUB_MOMENTUM[k] for k in ("price", "earn", "factor")},
    )
    horizon = _norm_group(
        {k: sm_in.get(k, DEFAULT_SUB_MOMENTUM[k]) for k in ("mom1", "mom6", "mom12")},
        {k: DEFAULT_SUB_MOMENTUM[k] for k in ("mom1", "mom6", "mom12")},
    )
    sub_momentum_out = {**pillar, **horizon}

    reason = str(data.get("reason") or "").strip() or DEFAULT_WEIGHTS["reason"]
    reason = re.sub(r"\[\d+(?:\]\[\d+)*\]", "", reason)
    reason = re.sub(r"\s{2,}", " ", reason).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.。!?？])\s+", reason) if s.strip()]
    if len(sentences) > 4:
        reason = " ".join(sentences[:4])

    return {
        "value": max(0, min(100, v)),
        "quality": max(0, min(100, q)),
        "momentum": max(0, min(100, m)),
        "sub_value": _norm_group(sub_value, DEFAULT_SUB_VALUE),
        "sub_quality": _norm_group(sub_quality, DEFAULT_SUB_QUALITY),
        "sub_momentum": sub_momentum_out,
        "reason": reason,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(data.get("source") or "unknown"),
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    # nested JSON: find outermost braces
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blob = text[start : end + 1]
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            # trim trailing junk
            for i in range(len(blob), 0, -1):
                try:
                    return json.loads(blob[:i])
                except json.JSONDecodeError:
                    continue
    return None


def save_ai_weights(weights: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_weights(weights)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def load_ai_weights() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return _normalize_weights(data)
    except Exception:
        return None


def _call_perplexity() -> dict[str, Any] | None:
    api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip().strip('"').strip("'")
    if not api_key:
        print("[AI] PERPLEXITY_API_KEY 없음")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""당신은 한국 주식(KRX) 퀀트 포트폴리오 매크로 전략가입니다. 오늘 날짜는 {today}입니다.

최근 한국/글로벌 뉴스, 기업 공시, 금리·환율·유동성 시황을 바탕으로
월간 리밸런싱용 팩터 비중을 제안하세요.

반드시 아래 JSON만 출력하세요. 마크다운/설명 금지.
{{
  "value": <0-100>,
  "quality": <0-100>,
  "momentum": <0-100>,
  "sub_value": {{"per":0-100, "pbr":0-100, "psr":0-100, "ev":0-100}},
  "sub_quality": {{"roe":0-100, "opm":0-100, "gpm":0-100, "fscore":0-100}},
  "sub_momentum": {{
    "price":0-100, "earn":0-100, "factor":0-100,
    "mom1":0-100, "mom6":0-100, "mom12":0-100
  }},
  "reason": "<한국어 2~4문장. 매크로 비중과 세부(특히 가격/이익/팩터 모멘텀) 선택 근거>"
}}

규칙:
1) value+quality+momentum = 100
2) sub_value 합=100, sub_quality 합=100
3) sub_momentum.price+earn+factor = 100  (가격·이익·팩터 모멘텀 배분)
4) sub_momentum.mom1+mom6+mom12 = 100  (가격 모멘텀 내부 Horizon)
5) 침체·고금리·실적 불확실 → value/quality·earn↑ / 강세·유동성↑ → momentum·price·factor↑
6) reason에 구체적 시황 근거 포함
"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": os.getenv("PERPLEXITY_MODEL", "sonar-pro"),
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "You are a KRX quant macro strategist. Reply with valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    try:
        resp = requests.post(PERPLEXITY_URL, headers=headers, json=payload, timeout=75)
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
            print(f"[AI] Perplexity JSON 파싱 실패: {content[:400]}")
            return None
        parsed["source"] = "perplexity"
        return parsed
    except Exception as e:
        print(f"[AI] Perplexity 호출 실패: {e}")
        return None


def _call_gemini() -> dict[str, Any] | None:
    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip('"')
    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = (
        "한국 주식 퀀트 매크로+세부 비중 JSON만 출력. "
        'keys: value,quality,momentum,sub_value{per,pbr,psr,ev},'
        "sub_quality{roe,opm,gpm,fscore},"
        "sub_momentum{price,earn,factor,mom1,mom6,mom12},reason. "
        "각 그룹 합 100. reason 한국어 2~4문장."
    )
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=45,
        )
        resp.raise_for_status()
        parts = (
            resp.json()
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        text = "".join(p.get("text", "") for p in parts)
        parsed = _extract_json_object(text)
        if parsed:
            parsed["source"] = f"gemini:{model}"
        return parsed
    except Exception as e:
        print(f"[AI] Gemini 호출 실패: {e}")
        return None


def get_monthly_factor_weights(force_refresh: bool = True) -> dict[str, Any]:
    if not force_refresh:
        cached = load_ai_weights()
        if cached:
            return cached

    px = _call_perplexity()
    if px:
        return save_ai_weights(px)

    gm = _call_gemini()
    if gm:
        return save_ai_weights(gm)

    cached = load_ai_weights()
    if cached and cached.get("source") != "fallback":
        cached = dict(cached)
        cached["reason"] = (
            "AI API 호출에 실패해 직전 저장된 비중을 유지합니다. "
            + str(cached.get("reason", ""))
        )[:500]
        return cached

    fallback = dict(DEFAULT_WEIGHTS)
    fallback["source"] = "fallback"
    return save_ai_weights(fallback)


if __name__ == "__main__":
    print(json.dumps(get_monthly_factor_weights(), ensure_ascii=False, indent=2))
