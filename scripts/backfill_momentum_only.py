# -*- coding: utf-8 -*-
"""
가격 모멘텀(mom_1m/6m/12m)만 재계산해 monthly_factor에 UPDATE.
다른 컬럼(PER, C9 성장, accrual 등)은 건드리지 않음.

예:
  python scripts/backfill_momentum_only.py --month 2026-06
  python scripts/backfill_momentum_only.py --month 2026-06 --dry-run
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
import time

import pandas as pd

# repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from factor_builder import _norm_ticker, compute_momentum  # noqa: E402

DB_PATH = os.path.join(ROOT, "data_cache", "quant_history.db")


def _f(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return float(v)


def main() -> None:
    p = argparse.ArgumentParser(description="모멘텀 컬럼만 재적재")
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--db", default=DB_PATH)
    args = p.parse_args()
    month = args.month.strip()

    conn = sqlite3.connect(args.db)
    tickers = [
        _norm_ticker(r[0])
        for r in conn.execute(
            "SELECT DISTINCT ticker FROM monthly_factor WHERE date = ?", (month,)
        ).fetchall()
    ]
    tickers = [t for t in tickers if t.startswith("A") and len(t) == 7 and t[1:].isdigit()]
    print(f"대상월 {month} | monthly_factor 유효티커 {len(tickers)}")

    before = conn.execute(
        """
        SELECT count(*) FROM monthly_factor
        WHERE date=? AND mom_12m IS NOT NULL
        """,
        (month,),
    ).fetchone()[0]
    n_all = conn.execute(
        "SELECT count(*) FROM monthly_factor WHERE date=?", (month,)
    ).fetchone()[0]
    print(f"재적재 전 mom_12m 비결측: {before}/{n_all} ({100*before/n_all:.1f}%)")

    t0 = time.time()
    print("daily_price 기반 모멘텀 계산 중...")
    mom_df = compute_momentum(conn, month)
    if mom_df.empty:
        print("❌ 모멘텀 계산 결과 없음 — daily_price 확인")
        conn.close()
        return
    mom_df["ticker"] = mom_df["ticker"].map(_norm_ticker)
    mom_df = mom_df[mom_df["ticker"].isin(set(tickers))].copy()
    print(f"계산 완료: {len(mom_df)}종목 / {time.time()-t0:.1f}s")

    ok1 = int(mom_df["mom_1m"].notna().sum())
    ok6 = int(mom_df["mom_6m"].notna().sum())
    ok12 = int(mom_df["mom_12m"].notna().sum())
    print(f"비결측 mom_1m={ok1} mom_6m={ok6} mom_12m={ok12}")

    if args.dry_run:
        print("dry-run: DB 미반영")
        conn.close()
        return

    cur = conn.cursor()
    rows = [
        (_f(r.mom_1m), _f(r.mom_6m), _f(r.mom_12m), month, r.ticker)
        for r in mom_df.itertuples(index=False)
    ]
    cur.executemany(
        """
        UPDATE monthly_factor
        SET mom_1m = ?, mom_6m = ?, mom_12m = ?
        WHERE date = ? AND ticker = ?
        """,
        rows,
    )
    conn.commit()
    updated = cur.rowcount

    after = conn.execute(
        """
        SELECT count(*) FROM monthly_factor
        WHERE date=? AND mom_12m IS NOT NULL
        """,
        (month,),
    ).fetchone()[0]
    print(f"✅ UPDATE 반영 rowcount합≈{updated}")
    print(f"재적재 후 mom_12m 비결측: {after}/{n_all} ({100*after/n_all:.1f}%)")
    conn.close()


if __name__ == "__main__":
    main()
