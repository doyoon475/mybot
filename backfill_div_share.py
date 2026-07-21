# -*- coding: utf-8 -*-
"""
Phase B6: QuantKing 배당수익률·주식수 증가율 → div_yield / share_growth 백필

예:
  python backfill_div_share.py
  python backfill_div_share.py --min-month 2024-01
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-month", default="2019-06")
    args = p.parse_args()

    conn = _connect()
    ensure_factor_columns(conn)
    files = latest_file_per_month(args.min_month)
    print(f"대상 월 {len(files)}개 (min={args.min_month})", flush=True)
    t0 = time.time()
    total_div = total_sh = 0
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
            for c in ("div_yield", "share_growth"):
                if c not in raw.columns:
                    raw[c] = float("nan")
                else:
                    raw[c] = pd.to_numeric(raw[c], errors="coerce")
            raw.loc[raw["div_yield"] <= 0, "div_yield"] = float("nan")

            rows = list(
                zip(
                    [_null(v) for v in raw["div_yield"].tolist()],
                    [_null(v) for v in raw["share_growth"].tolist()],
                    [month] * len(raw),
                    raw["ticker"].tolist(),
                )
            )
            conn.executemany(
                """
                UPDATE monthly_factor
                SET div_yield=?, share_growth=?
                WHERE date=? AND ticker=?
                """,
                rows,
            )
            conn.commit()
            nd = int(raw["div_yield"].notna().sum())
            ns = int(raw["share_growth"].notna().sum())
            total_div += nd
            total_sh += ns
            print(
                f"  [{i}/{len(files)}] {month}: div={nd} share={ns} | "
                f"{os.path.basename(path)[:42]}",
                flush=True,
            )
        except Exception as e:
            print(f"  [{i}] {month} 실패: {e}", flush=True)
    conn.close()
    print(
        f"✅ 완료 {time.time()-t0:.1f}s | div_yield≈{total_div} share_growth≈{total_sh}",
        flush=True,
    )


if __name__ == "__main__":
    main()
