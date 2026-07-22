# -*- coding: utf-8 -*-
"""
Release/업로드 전 DB 품질 게이트.

불완전한 monthly_factor(예: 최신월 PER 거의 없음)가 quant-db-latest 를
덮어쓰지 못하게 막는다.

환경변수:
  GATE_MIN_PER_COVERAGE   기본 0.80  (최신월 per>0 비율)
  GATE_MIN_ROWS           기본 500
  GATE_MAX_DROP_VS_PREV   기본 0.35  (직전월 대비 커버리지 하락 허용폭)
  GATE_SKIP=1             게이트 생략 (비상용)
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
    """
    최신·직전 monthly_factor 월의 per 커버리지.
    DB는 읽기 전용으로 연다 (적재 중 프로세스와 충돌 최소화).
    """
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


def evaluate_gate(
    db_path: str,
    min_per_cov: Optional[float] = None,
    min_rows: Optional[int] = None,
    max_drop_vs_prev: Optional[float] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    통과 여부, 메시지, 상세 dict.
    """
    if os.getenv("GATE_SKIP", "").lower() in ("1", "true", "yes"):
        return True, "GATE_SKIP=1 — 게이트 생략", {}

    min_per_cov = (
        _env_float("GATE_MIN_PER_COVERAGE", 0.80)
        if min_per_cov is None
        else min_per_cov
    )
    min_rows = _env_int("GATE_MIN_ROWS", 500) if min_rows is None else min_rows
    max_drop_vs_prev = (
        _env_float("GATE_MAX_DROP_VS_PREV", 0.35)
        if max_drop_vs_prev is None
        else max_drop_vs_prev
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

    if latest["n"] < min_rows:
        return (
            False,
            f"최신월 행 수 부족: {latest['n']} < {min_rows}. " + " | ".join(lines),
            info,
        )

    if latest["per_cov"] < min_per_cov:
        return (
            False,
            f"최신월 PER 커버리지 부족: {latest['per_cov']:.1%} < {min_per_cov:.0%}. "
            + " | ".join(lines),
            info,
        )

    if prev and prev["per_cov"] >= min_per_cov:
        drop = prev["per_cov"] - latest["per_cov"]
        if drop > max_drop_vs_prev:
            return (
                False,
                f"직전월 대비 PER 커버리지 급락: -{drop:.1%} "
                f"(허용 {max_drop_vs_prev:.0%}). " + " | ".join(lines),
                info,
            )

    return True, "OK — " + " | ".join(lines), info


def assert_release_quality(db_path: str) -> None:
    """실패 시 SystemExit(2)."""
    ok, msg, _ = evaluate_gate(db_path)
    if ok:
        print(f"✅ DB 품질 게이트: {msg}", flush=True)
        return
    print(f"❌ DB 품질 게이트 실패 — Release 업로드 중단:\n   {msg}", flush=True)
    print(
        "   (비상 시 GATE_SKIP=1 로 우회 가능. "
        "임계값: GATE_MIN_PER_COVERAGE / GATE_MIN_ROWS / GATE_MAX_DROP_VS_PREV)",
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
