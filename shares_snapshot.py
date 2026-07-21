# -*- coding: utf-8 -*-
"""
Phase C8: 월별 상장주식수/시총 스냅샷 (monthly_shares)

- 히스토리: QuantKing 파일에서 주식수·시총 추출
- 현재/향후: FDR StockListing (QuantKing 독립)
- 옵션: monthly_shares YoY → monthly_factor.share_growth 보완

예:
  python shares_snapshot.py --from-quantking --min-month 2019-06
  python shares_snapshot.py --fdr-current
  python shares_snapshot.py --fill-share-growth
  python shares_snapshot.py --all
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
from datetime import datetime
from typing import Optional

import pandas as pd

from factor_builder import _connect, _norm_ticker, load_listings_marcap, month_end_closes


DB_PATH = os.path.abspath("./data_cache/quant_history.db")


def ensure_shares_table(conn: Optional[sqlite3.Connection] = None) -> None:
    own = conn is None
    if own:
        conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monthly_shares (
                date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                stocks REAL,
                marcap REAL,
                close REAL,
                source TEXT,
                PRIMARY KEY (date, ticker),
                FOREIGN KEY (ticker) REFERENCES stock_master(ticker)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_monthly_shares_date ON monthly_shares(date)"
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _null(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return float(v)


def _pick_stocks_col(cols: list[str]) -> Optional[str]:
    for c in cols:
        if c == "상장주식수 (만주)":
            return c
        if c == "해당하는 보통주 주식수":
            return c
    for c in cols:
        if "상장주식수" in c and "자사주" not in c and "100" not in c:
            return c
    return None


def _pick_marcap_col(cols: list[str]) -> Optional[str]:
    for c in cols:
        if c == "시가총액 (억)":
            return c
        if c == "보통주 + 우선주의 합산 시가총액":
            return c
        if c.startswith("시가총액=") or c == "시가총액":
            return c
    for c in cols:
        if "합산 시가총액" in c:
            return c
    return None


def _normalize_stocks(series: pd.Series, col_name: str) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    # 만주 단위 → 주
    if "만주" in col_name:
        return s * 10_000.0
    return s


def _normalize_marcap(series: pd.Series, col_name: str) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if "억" in col_name:
        return s * 100_000_000.0
    return s


def _upsert_shares(conn: sqlite3.Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT OR REPLACE INTO monthly_shares
        (date, ticker, stocks, marcap, close, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def backfill_from_quantking(min_month: str = "2019-06") -> None:
    from backfill_factor_gaps import latest_file_per_month
    from raw_data_etl import read_quant_table

    conn = _connect()
    ensure_shares_table(conn)
    files = latest_file_per_month(min_month)
    print(f"📦 QuantKing → monthly_shares | 대상 월 {len(files)}", flush=True)
    t0 = time.time()
    total = 0
    for i, (month, path) in enumerate(sorted(files.items()), 1):
        try:
            raw = read_quant_table(path)
            cols = list(raw.columns.astype(str))
            # ticker
            tcol = None
            for c in cols:
                if c.startswith("코드") or "기업코드" in c or c == "코드":
                    tcol = c
                    break
            if tcol is None:
                print(f"  [{i}] {month} 티커 컬럼 없음", flush=True)
                continue
            scol = _pick_stocks_col(cols)
            mcol = _pick_marcap_col(cols)
            if scol is None:
                print(f"  [{i}] {month} 주식수 컬럼 없음", flush=True)
                continue

            df = pd.DataFrame()
            df["ticker"] = raw[tcol].map(_norm_ticker)
            df["stocks"] = _normalize_stocks(raw[scol], scol)
            if mcol:
                df["marcap"] = _normalize_marcap(raw[mcol], mcol)
            else:
                df["marcap"] = float("nan")

            closes = month_end_closes(conn, month)
            df = df.dropna(subset=["ticker"]).drop_duplicates("ticker")
            df = df[df["ticker"].str.match(r"^A\d{6}$", na=False)]

            close_map = {}
            try:
                if not closes.empty:
                    close_map = dict(
                        zip(closes["ticker"], pd.to_numeric(closes["close"], errors="coerce"))
                    )
            except Exception:
                pass

            rows = []
            for r in df.itertuples(index=False):
                stocks = _null(r.stocks)
                marcap = _null(r.marcap)
                close = _null(close_map.get(r.ticker))
                if marcap is None and stocks is not None and close is not None:
                    marcap = stocks * close
                if stocks is None and marcap is None:
                    continue
                rows.append((month, r.ticker, stocks, marcap, close, "quantking"))
            n = _upsert_shares(conn, rows)
            total += n
            print(
                f"  [{i}/{len(files)}] {month}: {n}행 | {os.path.basename(path)[:40]}",
                flush=True,
            )
            time.sleep(0.05)
        except Exception as e:
            print(f"  [{i}] {month} 실패: {e}", flush=True)
    conn.close()
    print(f"✅ QuantKing 백필 완료 {time.time()-t0:.1f}s | {total}행", flush=True)


def snapshot_from_fdr(target_month: Optional[str] = None) -> None:
    """현재 FDR 상장주식수/시총 → target_month(기본: 이번 달)."""
    month = target_month or datetime.now().strftime("%Y-%m")
    conn = _connect()
    ensure_shares_table(conn)
    print(f"📡 FDR StockListing → monthly_shares [{month}]", flush=True)
    listing = load_listings_marcap()
    if listing.empty:
        print("⚠️ FDR 리스팅 비어 있음", flush=True)
        conn.close()
        return

    close_map = {}
    try:
        cldf = month_end_closes(conn, month)
        if not cldf.empty:
            close_map = dict(zip(cldf["ticker"], pd.to_numeric(cldf["close"], errors="coerce")))
    except Exception as e:
        print(f"⚠️ 월말 종가 조회 실패: {e}", flush=True)

    rows = []
    for _, r in listing.iterrows():
        ticker = r["ticker"]
        stocks = _null(r.get("stocks"))
        marcap = _null(r.get("marcap"))
        close = _null(close_map.get(ticker))
        if close is None:
            close = _null(r.get("list_close"))
        if marcap is None and stocks is not None and close is not None:
            marcap = stocks * close
        if stocks is None and marcap is None:
            continue
        rows.append((month, ticker, stocks, marcap, close, "fdr"))
    n = _upsert_shares(conn, rows)
    conn.close()
    print(f"✅ FDR 스냅샷 {n}행 적재 [{month}]", flush=True)


def fill_share_growth_from_shares(only_null: bool = True) -> None:
    """
    monthly_shares 주식수 YoY % → monthly_factor.share_growth 보완.
    only_null=True 이면 기존 QuantKing share_growth 는 유지.
    """
    conn = _connect()
    ensure_shares_table(conn)
    from factor_builder import ensure_factor_columns

    ensure_factor_columns(conn)

    df = pd.read_sql("SELECT date, ticker, stocks FROM monthly_shares", conn)
    df["stocks"] = pd.to_numeric(df["stocks"], errors="coerce")
    df = df.dropna(subset=["stocks"])
    stock_map = {(r.date, r.ticker): r.stocks for r in df.itertuples(index=False)}

    def prev_ym(ym: str) -> str:
        y, m = str(ym).split("-")[:2]
        return f"{int(y) - 1:04d}-{int(m):02d}"

    updates = []
    for (date, ticker), stocks in stock_map.items():
        prev = stock_map.get((prev_ym(date), ticker))
        if prev is None or prev == 0:
            continue
        chg = (stocks - prev) / prev * 100.0
        updates.append((chg, date, ticker))

    if not updates:
        print("⚠️ share_growth 보완할 행 없음", flush=True)
        conn.close()
        return

    if only_null:
        conn.executemany(
            """
            UPDATE monthly_factor
            SET share_growth=?
            WHERE date=? AND ticker=? AND share_growth IS NULL
            """,
            updates,
        )
    else:
        conn.executemany(
            """
            UPDATE monthly_factor
            SET share_growth=?
            WHERE date=? AND ticker=?
            """,
            updates,
        )
    conn.commit()
    # 실제 반영 수 추정
    n = conn.execute(
        "SELECT SUM(CASE WHEN share_growth IS NOT NULL THEN 1 ELSE 0 END) FROM monthly_factor"
    ).fetchone()[0]
    conn.close()
    print(
        f"✅ share_growth 보완 후보 {len(updates)}행 "
        f"(only_null={only_null}) | DB non-null≈{n}",
        flush=True,
    )


def main():
    p = argparse.ArgumentParser(description="Phase C8 monthly_shares snapshot")
    p.add_argument("--from-quantking", action="store_true")
    p.add_argument("--fdr-current", action="store_true")
    p.add_argument("--fill-share-growth", action="store_true")
    p.add_argument("--overwrite-share-growth", action="store_true")
    p.add_argument("--min-month", default="2019-06")
    p.add_argument("--month", default=None, help="FDR 스냅샷 대상 YYYY-MM")
    p.add_argument("--all", action="store_true", help="quantking+fdr+fill")
    args = p.parse_args()

    if args.all:
        args.from_quantking = True
        args.fdr_current = True
        args.fill_share_growth = True

    if not (args.from_quantking or args.fdr_current or args.fill_share_growth):
        p.print_help()
        return

    ensure_shares_table()
    if args.from_quantking:
        backfill_from_quantking(args.min_month)
    if args.fdr_current:
        snapshot_from_fdr(args.month)
    if args.fill_share_growth:
        fill_share_growth_from_shares(only_null=not args.overwrite_share_growth)


if __name__ == "__main__":
    main()
