# -*- coding: utf-8 -*-
"""
Phase A3–A4 백필: DART 전체재무제표(finstate_all)로 accrual / fcf_yield 만 UPDATE.
기존 PER/모멘텀 등 다른 컬럼은 건드리지 않음.

예:
  python backfill_accrual_fcf.py --month 2026-07 --limit 40
  python backfill_accrual_fcf.py --month 2026-07
  python backfill_accrual_fcf.py --all-months
  python backfill_accrual_fcf.py --all-months --sleep 0.5
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from factor_builder import (
    DartQuotaExceeded,
    _connect,
    _init_dart,
    _norm_ticker,
    compute_accrual,
    compute_fcf_yield,
    ensure_factor_columns,
    extract_fundamentals,
    fetch_finstate_all_cached,
    fetch_finstate_cached,
    is_financial_sector,
    load_listings_marcap,
    merge_fundamentals,
)

PROGRESS_PATH = os.path.abspath("./data_cache/accrual_fcf_progress.txt")
LIVE_LOG = os.path.abspath("./data_cache/accrual_fcf_live.log")


def _fin_year(ym: str, override: Optional[int] = None) -> int:
    if override is not None:
        return override
    y = int(ym[:4])
    m = int(ym[5:7])
    return y - 2 if m <= 3 else y - 1


def _write_progress(
    *,
    done: int,
    total: int,
    ok_acc: int,
    ok_fcf: int,
    current: str,
    t0: float,
    phase: str = "accrual_fcf",
) -> None:
    elapsed = time.time() - t0
    rate = done / elapsed if elapsed > 0 and done else 0
    eta = (total - done) / rate if rate > 0 else 0
    pct = 100.0 * done / total if total else 0
    body = (
        f"phase={phase}\n"
        f"progress={done}/{total}\n"
        f"percent={pct:.2f}\n"
        f"ok_accrual={ok_acc}\n"
        f"ok_fcf={ok_fcf}\n"
        f"elapsed_sec={elapsed:.0f}\n"
        f"eta_sec={eta:.0f}\n"
        f"current={current}\n"
        f"updated={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(body)
    line = (
        f"A3 [{done}/{total} {pct:.1f}%] acc={ok_acc} fcf={ok_fcf} "
        f"elapsed={elapsed/60:.0f}m ETA={eta/60:.0f}m now={current}  "
        f"{time.strftime('%H:%M:%S')}\n"
    )
    with open(LIVE_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    print(line.rstrip(), flush=True)


def _quiet_fetch(fn, *args, **kwargs):
    """OpenDartReader의 status 013 print 스팸을 숨김."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*args, **kwargs)


def _log_line(msg: str) -> None:
    print(msg, flush=True)
    os.makedirs(os.path.dirname(LIVE_LOG), exist_ok=True)
    with open(LIVE_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _backfill_month(
    conn,
    dart,
    month: str,
    fin_year: int,
    master: pd.DataFrame,
    marcap_map: Dict[str, float],
    sleep_sec: float,
    skip_filled: bool,
    *,
    month_i: int = 1,
    month_n: int = 1,
    t0: Optional[float] = None,
) -> Tuple[int, int, int]:
    """한 달 백필. 반환: (처리시도, ok_acc, ok_fcf)"""
    cur = conn.cursor()
    ok_acc = ok_fcf = tried = empty = 0
    t_month = time.time()
    n_master = len(master)

    if skip_filled:
        filled = {
            r[0]
            for r in cur.execute(
                """
                SELECT ticker FROM monthly_factor
                WHERE date=? AND accrual IS NOT NULL AND fcf_yield IS NOT NULL
                """,
                (month,),
            )
        }
    else:
        filled = set()

    for row in master.itertuples(index=False):
        ticker, sector = row.ticker, row.sector
        if ticker in filled:
            continue
        tried += 1
        # DART 013 등 라이브러리 print 억제
        try:
            df_all = _quiet_fetch(
                fetch_finstate_all_cached, dart, ticker, fin_year, sleep_sec=sleep_sec
            )
        except DartQuotaExceeded:
            conn.commit()
            raise
        if df_all.empty:
            empty += 1
            if tried % 25 == 0 or tried == 1:
                elapsed = time.time() - (t0 or t_month)
                _log_line(
                    f"A3 [{month_i}/{month_n}] {month} ticker={tried}/{n_master} "
                    f"{ticker} | acc={ok_acc} fcf={ok_fcf} empty={empty} "
                    f"elapsed={elapsed/60:.1f}m"
                )
            # 캐시 미스 + 연속 empty가 많으면 한도/장애 가능성 → 조기 경고만 (020은 예외로 중단)
            continue
        fund = extract_fundamentals(df_all)
        try:
            df_bs = _quiet_fetch(
                fetch_finstate_cached, dart, ticker, fin_year, sleep_sec=0.05
            )
        except DartQuotaExceeded:
            conn.commit()
            raise
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

        if tried % 25 == 0 or tried == 1 or tried == n_master:
            elapsed = time.time() - (t0 or t_month)
            _log_line(
                f"A3 [{month_i}/{month_n}] {month} ticker={tried}/{n_master} "
                f"{ticker} | acc={ok_acc} fcf={ok_fcf} empty={empty} "
                f"elapsed={elapsed/60:.1f}m"
            )
            conn.commit()
            with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
                f.write(
                    f"phase=accrual_fcf\n"
                    f"progress={month_i-1}/{month_n}\n"
                    f"month={month}\n"
                    f"ticker={tried}/{n_master}\n"
                    f"ok_accrual={ok_acc}\n"
                    f"ok_fcf={ok_fcf}\n"
                    f"empty={empty}\n"
                    f"current={ticker}\n"
                    f"elapsed_sec={elapsed:.0f}\n"
                    f"updated={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                )

    conn.commit()
    return tried, ok_acc, ok_fcf


def _load_month_master(conn, month: str, limit: Optional[int]) -> pd.DataFrame:
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
    if limit:
        master = master.head(limit)
    return master


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", type=str, default=None, help="YYYY-MM (기본: DB 최신월)")
    p.add_argument("--all-months", action="store_true", help="monthly_factor 전 월 백필")
    p.add_argument("--limit", type=int, default=None, help="월별 종목 수 제한(테스트)")
    p.add_argument("--sleep", type=float, default=0.5)
    p.add_argument("--year", type=int, default=None, help="재무연도 고정(단일 월용)")
    p.add_argument(
        "--force",
        action="store_true",
        help="이미 accrual+fcf 있는 종목도 다시 계산",
    )
    args = p.parse_args()

    conn = _connect()
    ensure_factor_columns(conn)

    if args.all_months:
        months: List[str] = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM monthly_factor ORDER BY date"
            ).fetchall()
        ]
    else:
        month = args.month or conn.execute(
            "SELECT max(date) FROM monthly_factor"
        ).fetchone()[0]
        if not month:
            print("❌ monthly_factor 비어 있음")
            return
        months = [month]

    if not months:
        print("❌ 대상 월 없음")
        return

    listing = load_listings_marcap()
    marcap_map: Dict[str, float] = {}
    if not listing.empty and "marcap" in listing.columns:
        marcap_map = listing.set_index("ticker")["marcap"].to_dict()

    dart = _init_dart()
    if dart is None:
        print("❌ DART 초기화 실패 — API 키/패키지 확인")
        return

    skip_filled = not args.force
    total = len(months)
    print(
        f"🚀 accrual/fcf 백필 | months={total} | sleep={args.sleep} | "
        f"skip_filled={skip_filled}",
        flush=True,
    )
    if os.path.exists(LIVE_LOG):
        os.remove(LIVE_LOG)

    t0 = time.time()
    sum_acc = sum_fcf = 0
    for i, ym in enumerate(months, 1):
        fy = _fin_year(ym, args.year if not args.all_months else None)
        master = _load_month_master(conn, ym, args.limit)
        if args.limit and i == 1:
            print(f"🔬 limit={args.limit}", flush=True)
        _log_line(f"—— [{i}/{total}] {ym} fin_year={fy} tickers={len(master)} ——")
        try:
            tried, ok_acc, ok_fcf = _backfill_month(
                conn,
                dart,
                ym,
                fy,
                master,
                marcap_map,
                args.sleep,
                skip_filled,
                month_i=i,
                month_n=total,
                t0=t0,
            )
        except DartQuotaExceeded as e:
            msg = (
                f"⛔ DART 일일 한도 초과(020) — 백필 중단 at {ym} fin_year={fy}. "
                f"{e} | 내일 한도 리셋 후 같은 명령으로 재개 "
                f"(skip_filled=True라 이미 채운 월은 건너뜀)."
            )
            _log_line(msg)
            _write_progress(
                done=max(0, i - 1),
                total=total,
                ok_acc=sum_acc,
                ok_fcf=sum_fcf,
                current=f"QUOTA_HALT@{ym}",
                t0=t0,
            )
            conn.close()
            raise SystemExit(2) from e
        sum_acc += ok_acc
        sum_fcf += ok_fcf
        _write_progress(
            done=i,
            total=total,
            ok_acc=sum_acc,
            ok_fcf=sum_fcf,
            current=f"{ym}(+{ok_acc}/{ok_fcf},tried={tried})",
            t0=t0,
        )

    conn.close()
    print(
        f"✅ 전체 완료 {time.time()-t0:.1f}s | months={total} | "
        f"accrual_updates≈{sum_acc} | fcf_updates≈{sum_fcf}",
        flush=True,
    )
    _write_progress(
        done=total,
        total=total,
        ok_acc=sum_acc,
        ok_fcf=sum_fcf,
        current="DONE",
        t0=t0,
    )


if __name__ == "__main__":
    main()
