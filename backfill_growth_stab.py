# -*- coding: utf-8 -*-
"""
Phase B5: QuantKing 3년 성장률 → growth_stab 백필
월별 최신 파일에서 sales_g3y/op_g3y/ni_g3y/growth_stab 만 UPDATE.

예:
  python backfill_growth_stab.py
  python backfill_growth_stab.py --min-month 2024-01
"""
from __future__ import annotations

import argparse
import os
import time

import pandas as pd

from backfill_factor_gaps import latest_file_per_month, load_mapped
from factor_builder import _connect, ensure_factor_columns
from factor_extras import compute_growth_stab


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--min-month", default="2019-06")
    args = p.parse_args()

    conn = _connect()
    ensure_factor_columns(conn)
    files = latest_file_per_month(args.min_month)
    print(f"대상 월 {len(files)}개 (min={args.min_month})")
    t0 = time.time()
    total = 0
    for i, (month, path) in enumerate(sorted(files.items(), reverse=True), 1):
        try:
            df = load_mapped(path)
            if df.empty:
                print(f"  [{i}] {month} 빈 DF")
                continue
            # load_mapped may not include g3y — re-map via raw_data_etl
            from raw_data_etl import map_factor_columns, read_quant_table

            raw = map_factor_columns(read_quant_table(path)).copy()
            if "ticker" not in raw.columns:
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
            for c in ("sales_g3y", "op_g3y", "ni_g3y"):
                if c not in raw.columns:
                    raw[c] = float("nan")
                else:
                    raw[c] = pd.to_numeric(raw[c], errors="coerce")
            raw["growth_stab"] = compute_growth_stab(raw)

            rows = []
            for _, r in raw.iterrows():
                rows.append(
                    (
                        None if pd.isna(r.get("sales_g3y")) else float(r["sales_g3y"]),
                        None if pd.isna(r.get("op_g3y")) else float(r["op_g3y"]),
                        None if pd.isna(r.get("ni_g3y")) else float(r["ni_g3y"]),
                        None if pd.isna(r.get("growth_stab")) else float(r["growth_stab"]),
                        month,
                        r["ticker"],
                    )
                )
            conn.executemany(
                """
                UPDATE monthly_factor
                SET sales_g3y=?, op_g3y=?, ni_g3y=?, growth_stab=?
                WHERE date=? AND ticker=?
                """,
                rows,
            )
            conn.commit()
            n = int(raw["growth_stab"].notna().sum())
            total += n
            print(f"  [{i}/{len(files)}] {month}: growth_stab={n} | {os.path.basename(path)[:42]}")
        except Exception as e:
            print(f"  [{i}] {month} 실패: {e}")
    conn.close()
    print(f"✅ 완료 {time.time()-t0:.1f}s | growth_stab 갱신 합계≈{total}")


if __name__ == "__main__":
    main()
