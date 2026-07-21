# -*- coding: utf-8 -*-
"""
Phase B7: QuantKing 자사주 비중 → treasury_pct / treasury_chg 백필

- 신형: (현재 보통주 자사주비중 - 1년전 …) → treasury_chg 직접
- 구형: 자사주 비중 (%) → treasury_pct, 이후 YoY 차분으로 treasury_chg 보완

예:
  python backfill_treasury.py
  python backfill_treasury.py --min-month 2024-01
"""
from __future__ import annotations

import argparse
import os
import time

import pandas as pd

from backfill_factor_gaps import latest_file_per_month
from factor_builder import _connect, ensure_factor_columns
from raw_data_etl import map_factor_columns, read_quant_table


def _null(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return float(v)


def _prev_year_month(ym: str) -> str:
    y, m = str(ym).split("-")[:2]
    return f"{int(y) - 1:04d}-{int(m):02d}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-month", default="2019-06")
    args = p.parse_args()

    conn = _connect()
    ensure_factor_columns(conn)
    files = latest_file_per_month(args.min_month)
    print(f"대상 월 {len(files)}개 (min={args.min_month})", flush=True)
    t0 = time.time()
    total_pct = total_chg = 0

    for i, (month, path) in enumerate(sorted(files.items()), 1):
        try:
            raw = map_factor_columns(read_quant_table(path)).copy()
            if "ticker" not in raw.columns:
                print(f"  [{i}] {month} 티커 없음", flush=True)
                continue
            t = raw["ticker"].astype(str).str.strip()
            digits = (
                t.str.replace(r"^A", "", regex=True)
                .str.replace(r"\D", "", regex=True)
                .str.zfill(6)
                .str[-6:]
            )
            raw["ticker"] = "A" + digits
            raw = raw[raw["ticker"].str.match(r"^A\d{6}$", na=False)].copy()
            raw = raw.drop_duplicates(subset=["ticker"], keep="last")
            for c in ("treasury_pct", "treasury_chg"):
                if c not in raw.columns:
                    raw[c] = float("nan")
                else:
                    raw[c] = pd.to_numeric(raw[c], errors="coerce")

            rows = list(
                zip(
                    [_null(v) for v in raw["treasury_pct"].tolist()],
                    [_null(v) for v in raw["treasury_chg"].tolist()],
                    [month] * len(raw),
                    raw["ticker"].tolist(),
                )
            )
            conn.executemany(
                """
                UPDATE monthly_factor
                SET treasury_pct=?, treasury_chg=?
                WHERE date=? AND ticker=?
                """,
                rows,
            )
            conn.commit()
            np_ = int(raw["treasury_pct"].notna().sum())
            nc = int(raw["treasury_chg"].notna().sum())
            total_pct += np_
            total_chg += nc
            print(
                f"  [{i}/{len(files)}] {month}: pct={np_} chg={nc} | "
                f"{os.path.basename(path)[:42]}",
                flush=True,
            )
        except Exception as e:
            print(f"  [{i}] {month} 실패: {e}", flush=True)

    # 구형 월: treasury_chg 결측 → 동일 티커 12개월 전 treasury_pct 차분
    print("⏳ treasury_chg YoY 보완 (pct 기반)...", flush=True)
    df = pd.read_sql(
        "SELECT date, ticker, treasury_pct, treasury_chg FROM monthly_factor",
        conn,
    )
    df["treasury_pct"] = pd.to_numeric(df["treasury_pct"], errors="coerce")
    df["treasury_chg"] = pd.to_numeric(df["treasury_chg"], errors="coerce")
    pct_map = {
        (r.date, r.ticker): r.treasury_pct
        for r in df.dropna(subset=["treasury_pct"]).itertuples(index=False)
    }
    fill_rows = []
    for r in df.itertuples(index=False):
        if pd.notna(r.treasury_chg):
            continue
        if pd.isna(r.treasury_pct):
            continue
        prev = pct_map.get((_prev_year_month(str(r.date)), r.ticker))
        if prev is None or pd.isna(prev):
            continue
        fill_rows.append((float(r.treasury_pct) - float(prev), str(r.date), r.ticker))
    if fill_rows:
        conn.executemany(
            """
            UPDATE monthly_factor
            SET treasury_chg=?
            WHERE date=? AND ticker=? AND treasury_chg IS NULL
            """,
            fill_rows,
        )
        conn.commit()
    print(f"  YoY 보완 {len(fill_rows)}행", flush=True)

    conn.close()
    print(
        f"✅ 완료 {time.time()-t0:.1f}s | treasury_pct≈{total_pct} "
        f"direct_chg≈{total_chg} yoy_fill≈{len(fill_rows)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
