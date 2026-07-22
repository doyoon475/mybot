# -*- coding: utf-8 -*-
"""
Release/업로드 전 DB 품질 게이트.

빈 달(예: 최신월 PER/PBR 거의 없음)이 quant-db-latest 를 덮지 못하게 막되,
정상 운영 달(PER~50~60%, PBR 높음)은 통과시킨다.

규칙 (AND/OR):
  1) 행 수 >= GATE_MIN_ROWS (기본 500)
  2) 재난 하한: per < GATE_DISASTER_PER(0.10) AND pbr < GATE_DISASTER_PBR(0.20)
     → 무조건 실패
  3) 운영 통과: per >= GATE_MIN_PER(0.50) OR pbr >= GATE_MIN_PBR(0.80)
  4) 직전월이 '건강'(per>=MIN_PER 또는 pbr>=MIN_PBR)인데
     최신월 per가 GATE_MAX_DROP_VS_PREV(0.35) 이상 급락 → 실패
     (PBR 급락도 동일 임계로 검사)

환경변수:
  GATE_MIN_ROWS, GATE_MIN_PER_COVERAGE, GATE_MIN_PBR_COVERAGE
  GATE_DISASTER_PER, GATE_DISASTER_PBR, GATE_MAX_DROP_VS_PREV
  GATE_SKIP=1  비상 생략
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Any, Optional


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def latest_factor_coverage(db_path: str) -> dict[str, Any]:
    """최신·직전 monthly_factor 월의 per/pbr/roe 커버리지 (읽기 전용)."""
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        months = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM monthly_factor ORDER BY date DESC LIMIT 2"
            ).fetchall()
        ]
        if not months:
            return {
                "ok": False,
                "reason": "monthly_factor 행 없음",
                "latest": None,
                "prev": None,
            }

        def _stats(ym: str) -> dict[str, Any]:
            n, per_ok, pbr_ok, roe_ok = conn.execute(
                """
                SELECT
                  COUNT(*),
                  SUM(CASE WHEN per IS NOT NULL AND per > 0 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN pbr IS NOT NULL AND pbr > 0 THEN 1 ELSE 0 END),
                  SUM(CASE WHEN roe IS NOT NULL THEN 1 ELSE 0 END)
                FROM monthly_factor
                WHERE date = ?
                """,
                (ym,),
            ).fetchone()
            n = int(n or 0)
            per_ok = int(per_ok or 0)
            pbr_ok = int(pbr_ok or 0)
            roe_ok = int(roe_ok or 0)
            return {
                "date": ym,
                "n": n,
                "per_ok": per_ok,
                "pbr_ok": pbr_ok,
                "roe_ok": roe_ok,
                "per_cov": (per_ok / n) if n else 0.0,
                "pbr_cov": (pbr_ok / n) if n else 0.0,
                "roe_cov": (roe_ok / n) if n else 0.0,
            }

        latest = _stats(months[0])
        prev = _stats(months[1]) if len(months) > 1 else None
        return {"ok": True, "latest": latest, "prev": prev, "reason": None}
    finally:
        conn.close()


def _month_healthy(m: dict[str, Any], min_per: float, min_pbr: float) -> bool:
    return m["per_cov"] >= min_per or m["pbr_cov"] >= min_pbr


def evaluate_gate(
    db_path: str,
    min_per_cov: Optional[float] = None,
    min_pbr_cov: Optional[float] = None,
    min_rows: Optional[int] = None,
    max_drop_vs_prev: Optional[float] = None,
    disaster_per: Optional[float] = None,
    disaster_pbr: Optional[float] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """통과 여부, 메시지, 상세 dict."""
    if os.getenv("GATE_SKIP", "").lower() in ("1", "true", "yes"):
        return True, "GATE_SKIP=1 — 게이트 생략", {}

    min_per = (
        _env_float("GATE_MIN_PER_COVERAGE", 0.50)
        if min_per_cov is None
        else min_per_cov
    )
    min_pbr = (
        _env_float("GATE_MIN_PBR_COVERAGE", 0.80)
        if min_pbr_cov is None
        else min_pbr_cov
    )
    min_rows = _env_int("GATE_MIN_ROWS", 500) if min_rows is None else min_rows
    max_drop = (
        _env_float("GATE_MAX_DROP_VS_PREV", 0.35)
        if max_drop_vs_prev is None
        else max_drop_vs_prev
    )
    dis_per = (
        _env_float("GATE_DISASTER_PER", 0.10)
        if disaster_per is None
        else disaster_per
    )
    dis_pbr = (
        _env_float("GATE_DISASTER_PBR", 0.20)
        if disaster_pbr is None
        else disaster_pbr
    )

    info = latest_factor_coverage(db_path)
    if not info.get("ok"):
        return False, info.get("reason") or "커버리지 조회 실패", info

    latest = info["latest"]
    prev = info.get("prev")
    lines = [
        f"latest={latest['date']} n={latest['n']} "
        f"per={latest['per_cov']:.1%} pbr={latest['pbr_cov']:.1%} roe={latest['roe_cov']:.1%}"
    ]
    if prev:
        lines.append(
            f"prev={prev['date']} n={prev['n']} "
            f"per={prev['per_cov']:.1%} pbr={prev['pbr_cov']:.1%} roe={prev['roe_cov']:.1%}"
        )
    summary = " | ".join(lines)

    if latest["n"] < min_rows:
        return False, f"최신월 행 수 부족: {latest['n']} < {min_rows}. {summary}", info

    # 1) 재난 하한 — 빈 달
    if latest["per_cov"] < dis_per and latest["pbr_cov"] < dis_pbr:
        return (
            False,
            f"재난 하한(빈 달): per={latest['per_cov']:.1%} < {dis_per:.0%} "
            f"AND pbr={latest['pbr_cov']:.1%} < {dis_pbr:.0%}. {summary}",
            info,
        )

    # 2) 직전월 대비 급락 (직전월이 건강할 때만)
    if prev and _month_healthy(prev, min_per, min_pbr):
        per_drop = prev["per_cov"] - latest["per_cov"]
        pbr_drop = prev["pbr_cov"] - latest["pbr_cov"]
        if per_drop > max_drop:
            return (
                False,
                f"직전월 대비 PER 급락: -{per_drop:.1%} (허용 {max_drop:.0%}). {summary}",
                info,
            )
        if pbr_drop > max_drop:
            return (
                False,
                f"직전월 대비 PBR 급락: -{pbr_drop:.1%} (허용 {max_drop:.0%}). {summary}",
                info,
            )

    # 3) 운영 통과: PER 또는 PBR
    if not _month_healthy(latest, min_per, min_pbr):
        return (
            False,
            f"운영 커버리지 부족: per>={min_per:.0%} 또는 pbr>={min_pbr:.0%} 필요. {summary}",
            info,
        )

    return True, "OK — " + summary, info


def assert_release_quality(db_path: str) -> None:
    """실패 시 SystemExit(2)."""
    ok, msg, _ = evaluate_gate(db_path)
    if ok:
        print(f"✅ DB 품질 게이트: {msg}", flush=True)
        return
    print(f"❌ DB 품질 게이트 실패 — Release 업로드 중단:\n   {msg}", flush=True)
    print(
        "   (비상 시 GATE_SKIP=1. "
        "임계: GATE_MIN_PER/PBR, GATE_DISASTER_PER/PBR, GATE_MAX_DROP_VS_PREV)",
        flush=True,
    )
    raise SystemExit(2)


def main(argv: Optional[list[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    db = argv[0] if argv else os.path.abspath("./data_cache/quant_history.db")
    if not os.path.exists(db):
        print("DB 없음:", db)
        raise SystemExit(1)
    assert_release_quality(db)


if __name__ == "__main__":
    main()
