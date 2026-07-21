# -*- coding: utf-8 -*-
"""
Phase A3–A4 백필: DART 전체재무제표(finstate_all)로 accrual / fcf_yield 만 UPDATE.
기존 PER/모멘텀 등 다른 컬럼은 건드리지 않음.

예:
  python backfill_accrual_fcf.py --month 2026-07 --limit 40
  python backfill_accrual_fcf.py --month 2026-07
"""
from __future__ import annotations

import argparse
import time

import pandas as pd

from factor_builder import (
    _connect,
    _init_dart,
    _norm_ticker,
    compute_accrual,
    compute_fcf_yield,
    ensure_factor_columns,
    extract_fundamentals,
    fetch_finstate_all_cached,
    is_financial_sector,
    load_listings_marcap,
    merge_fundamentals,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", type=str, default=None, help="YYYY-MM (기본: DB 최신월)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--sleep", type=float, default=0.8)
    p.add_argument("--year", type=int, default=None, help="재무연도 (기본: month 기준 추정)")
    args = p.parse_args()

    conn = _connect()
    ensure_factor_columns(conn)
    month = args.month or conn.execute("SELECT max(date) FROM monthly_factor").fetchone()[0]
    if not month:
        print("❌ monthly_factor 비어 있음")
        return

    y = int(month[:4])
    m = int(month[5:7])
    fin_year = args.year or (y - 2 if m <= 3 else y - 1)

    master = pd.read_sql(
        """
        SELECT f.ticker, m.sector
        FROM monthly_factor f
        JOIN stock_master m ON f.ticker = m.ticker
        WHERE f.date = ? AND m.is_active = 1
        """,
        conn,
        params=(month,),
    )
    master["ticker"] = master["ticker"].map(_norm_ticker)
    if args.limit:
        master = master.head(args.limit)
        print(f"🔬 limit={args.limit}")

    print(f"대상월 {month} | 재무연도 {fin_year} | 종목 {len(master)}")
    listing = load_listings_marcap()
    marcap_map = {}
    if not listing.empty and "marcap" in listing.columns:
        marcap_map = listing.set_index("ticker")["marcap"].to_dict()

    dart = _init_dart()
    if dart is None:
        print("❌ DART 초기화 실패 — API 키/패키지 확인")
        return

    cur = conn.cursor()
    ok_acc = ok_fcf = 0
    t0 = time.time()
    for i, row in enumerate(master.itertuples(index=False), 1):
        ticker, sector = row.ticker, row.sector
        df_all = fetch_finstate_all_cached(dart, ticker, fin_year, sleep_sec=args.sleep)
        if df_all.empty:
            continue
        fund = extract_fundamentals(df_all)
        # 자산/NI 보강: 기존 BS 캐시가 있으면 merge
        from factor_builder import fetch_finstate_cached

        df_bs = fetch_finstate_cached(dart, ticker, fin_year, sleep_sec=0.05)
        if not df_bs.empty:
            fund = merge_fundamentals(extract_fundamentals(df_bs), fund)

        accrual = compute_accrual(fund)
        fcf = compute_fcf_yield(
            fund, marcap_map.get(ticker), financial=is_financial_sector(sector)
        )
        cur.execute(
            """
            UPDATE monthly_factor
            SET accrual = ?, fcf_yield = ?
            WHERE date = ? AND ticker = ?
            """,
            (accrual, fcf, month, ticker),
        )
        if accrual is not None:
            ok_acc += 1
        if fcf is not None:
            ok_fcf += 1
        if i % 20 == 0 or i == len(master):
            conn.commit()
            print(f"  [{i}/{len(master)}] accrual={ok_acc} fcf={ok_fcf}")

    conn.commit()
    conn.close()
    print(f"✅ 완료 {time.time()-t0:.1f}s | accrual {ok_acc} | fcf_yield {ok_fcf}")


if __name__ == "__main__":
    main()
