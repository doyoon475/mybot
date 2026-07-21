# -*- coding: utf-8 -*-
"""
Phase C9: DART 분기 재무 패널 → Growth / Surprise 근사

- per-reprt 캐시: {code}_{year}_{reprt}.parquet
- quarterly_fund 적재
- 동일 보고서코드 YoY → sales_g1y / op_g1y / ni_g1y / earn_surprise
- 최신 분기 기준 earn_mom 갱신(기존 NULL 또는 --overwrite)

예:
  python quarterly_panel.py --import-annual-cache
  python quarterly_panel.py --fetch --years 2 --limit 30 --sleep 1.0
  python quarterly_panel.py --apply
  python quarterly_panel.py --all --years 2 --sleep 1.0
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from factor_builder import (
    DART_CACHE_DIR,
    _connect,
    _dart_code,
    _init_dart,
    _norm_ticker,
    ensure_factor_columns,
    extract_fundamentals,
    merge_fundamentals,
)


REPRT_Q = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}
REPRT_ORDER = ("11013", "11012", "11014", "11011")


def ensure_quarterly_table(conn=None) -> None:
    own = conn is None
    if own:
        conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quarterly_fund (
                ticker TEXT NOT NULL,
                bsns_year INTEGER NOT NULL,
                reprt_code TEXT NOT NULL,
                fiscal_q INTEGER,
                revenue REAL,
                op_income REAL,
                net_income REAL,
                controlling_ni REAL,
                ebt REAL,
                equity REAL,
                assets REAL,
                liabilities REAL,
                gross_profit REAL,
                cfo REAL,
                capex REAL,
                source TEXT,
                PRIMARY KEY (ticker, bsns_year, reprt_code)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quarterly_fund_year ON quarterly_fund(bsns_year)"
        )
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def _cache_path_reprt(ticker: str, year: int, reprt: str) -> str:
    os.makedirs(DART_CACHE_DIR, exist_ok=True)
    return os.path.join(DART_CACHE_DIR, f"{_dart_code(ticker)}_{year}_{reprt}.parquet")


def _cache_path_reprt_all(ticker: str, year: int, reprt: str) -> str:
    os.makedirs(DART_CACHE_DIR, exist_ok=True)
    return os.path.join(
        DART_CACHE_DIR, f"{_dart_code(ticker)}_{year}_{reprt}_all.parquet"
    )


def _safe_yoy(cur, prev) -> Optional[float]:
    try:
        if cur is None or prev is None:
            return None
        cur_f, prev_f = float(cur), float(prev)
        if prev_f == 0 or np.isnan(cur_f) or np.isnan(prev_f):
            return None
        return (cur_f - prev_f) / abs(prev_f) * 100.0
    except (TypeError, ValueError):
        return None


def _null(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_finstate_reprt(
    dart,
    ticker: str,
    year: int,
    reprt: str,
    sleep_sec: float = 1.0,
) -> pd.DataFrame:
    path = _cache_path_reprt(ticker, year, reprt)
    miss = path + ".miss"
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    if os.path.exists(miss):
        return pd.DataFrame()

    # 연간(11011): 기존 annual 캐시 재사용
    if reprt == "11011":
        legacy = os.path.join(DART_CACHE_DIR, f"{_dart_code(ticker)}_{year}.parquet")
        if os.path.exists(legacy):
            try:
                df = pd.read_parquet(legacy)
                if not df.empty:
                    try:
                        df.to_parquet(path, index=False)
                    except Exception:
                        pass
                    return df
            except Exception:
                pass

    if dart is None:
        return pd.DataFrame()

    time.sleep(max(0.3, sleep_sec))
    code = _dart_code(ticker)
    try:
        df = dart.finstate(corp=code, bsns_year=year, reprt_code=reprt)
    except Exception:
        try:
            open(miss, "w", encoding="utf-8").close()
        except Exception:
            pass
        return pd.DataFrame()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or not hasattr(df, "columns"):
        try:
            open(miss, "w", encoding="utf-8").close()
        except Exception:
            pass
        return pd.DataFrame()
    try:
        df.to_parquet(path, index=False)
    except Exception:
        pass
    return df


def fetch_finstate_all_reprt(
    dart,
    ticker: str,
    year: int,
    reprt: str,
    sleep_sec: float = 1.0,
) -> pd.DataFrame:
    path = _cache_path_reprt_all(ticker, year, reprt)
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            pass

    if reprt == "11011":
        legacy = os.path.join(DART_CACHE_DIR, f"{_dart_code(ticker)}_{year}_all.parquet")
        if os.path.exists(legacy):
            try:
                df = pd.read_parquet(legacy)
                if not df.empty:
                    try:
                        df.to_parquet(path, index=False)
                    except Exception:
                        pass
                    return df
            except Exception:
                pass

    if dart is None:
        return pd.DataFrame()

    try:
        from OpenDartReader import dart_finstate
    except Exception:
        try:
            import OpenDartReader.dart_finstate as dart_finstate
        except Exception:
            return pd.DataFrame()

    time.sleep(max(0.3, sleep_sec))
    code = _dart_code(ticker)
    corp_code = code
    try:
        if hasattr(dart, "find_corp_code"):
            found = dart.find_corp_code(code)
            if found:
                corp_code = found
    except Exception:
        pass

    for fs_div in ("CFS", "OFS"):
        try:
            df = dart_finstate.finstate_all(
                dart.api_key, corp_code, year, reprt_code=reprt, fs_div=fs_div
            )
        except Exception:
            continue
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        try:
            df.to_parquet(path, index=False)
        except Exception:
            pass
        return df
    return pd.DataFrame()


def upsert_quarter_row(conn, ticker: str, year: int, reprt: str, fund: dict, source: str):
    ni = fund.get("net_income")
    conn.execute(
        """
        INSERT OR REPLACE INTO quarterly_fund
        (ticker, bsns_year, reprt_code, fiscal_q,
         revenue, op_income, net_income, controlling_ni, ebt,
         equity, assets, liabilities, gross_profit, cfo, capex, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticker,
            int(year),
            reprt,
            REPRT_Q.get(reprt),
            _null(fund.get("revenue")),
            _null(fund.get("op_income")),
            _null(ni),
            _null(ni),  # controlling_ni ≈ net_income (지배 우선 aliases)
            _null(fund.get("ebt")),
            _null(fund.get("equity")),
            _null(fund.get("assets")),
            _null(fund.get("liabilities")),
            _null(fund.get("gross_profit")),
            _null(fund.get("cfo")),
            _null(fund.get("capex")),
            source,
        ),
    )


def import_annual_cache() -> int:
    """기존 {code}_{year}.parquet 를 11011 분기로 이관."""
    conn = _connect()
    ensure_quarterly_table(conn)
    paths = glob.glob(os.path.join(DART_CACHE_DIR, "*_????.parquet"))
    paths = [p for p in paths if not p.endswith("_all.parquet") and "_110" not in os.path.basename(p)]
    n = 0
    for path in paths:
        base = os.path.basename(path)
        m = re.fullmatch(r"(\d{6})_(\d{4})\.parquet", base)
        if not m:
            continue
        code, year = m.group(1), int(m.group(2))
        ticker = _norm_ticker(code)
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if df.empty:
            continue
        fund = extract_fundamentals(df)
        all_path = os.path.join(DART_CACHE_DIR, f"{code}_{year}_all.parquet")
        if os.path.exists(all_path):
            try:
                fund = merge_fundamentals(fund, extract_fundamentals(pd.read_parquet(all_path)))
            except Exception:
                pass
        # per-reprt 캐시도 복사
        try:
            df.to_parquet(_cache_path_reprt(ticker, year, "11011"), index=False)
        except Exception:
            pass
        upsert_quarter_row(conn, ticker, year, "11011", fund, "dart_annual_import")
        n += 1
        if n % 500 == 0:
            conn.commit()
            print(f"  import {n}...", flush=True)
    conn.commit()
    conn.close()
    print(f"✅ annual 캐시 → quarterly_fund 11011: {n}행", flush=True)
    return n


def active_tickers(limit: Optional[int] = None) -> List[str]:
    conn = _connect()
    df = pd.read_sql(
        "SELECT ticker FROM stock_master WHERE is_active = 1 ORDER BY ticker",
        conn,
    )
    conn.close()
    tickers = [_norm_ticker(t) for t in df["ticker"].tolist()]
    if limit:
        tickers = tickers[:limit]
    return tickers


def fetch_panel(
    years: List[int],
    limit: Optional[int] = None,
    sleep_sec: float = 1.0,
    with_all: bool = False,
    reprts: Tuple[str, ...] = REPRT_ORDER,
) -> int:
    dart = _init_dart()
    conn = _connect()
    ensure_quarterly_table(conn)
    tickers = active_tickers(limit)
    print(
        f"📡 DART 분기 fetch | tickers={len(tickers)} years={years} reprts={list(reprts)}",
        flush=True,
    )
    saved = 0
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        for year in years:
            for reprt in reprts:
                try:
                    df = fetch_finstate_reprt(dart, ticker, year, reprt, sleep_sec)
                    if df.empty:
                        continue
                    fund = extract_fundamentals(df)
                    src = "dart_singl"
                    if with_all:
                        df_all = fetch_finstate_all_reprt(
                            dart, ticker, year, reprt, sleep_sec
                        )
                        if not df_all.empty:
                            fund = merge_fundamentals(fund, extract_fundamentals(df_all))
                            src = "dart_singl+all"
                    upsert_quarter_row(conn, ticker, year, reprt, fund, src)
                    saved += 1
                except Exception as e:
                    msg = str(e)
                    if "NoneType" not in msg:
                        print(f"  ⚠️ {ticker} {year}/{reprt}: {msg[:80]}", flush=True)
        if i % 50 == 0:
            conn.commit()
            print(
                f"  [{i}/{len(tickers)}] saved≈{saved} | {time.time()-t0:.0f}s",
                flush=True,
            )
    conn.commit()
    conn.close()
    print(f"✅ fetch 완료 saved={saved} | {time.time()-t0:.1f}s", flush=True)
    return saved


def latest_reprt_asof(ym: str) -> Tuple[int, str]:
    """공시 시차 반영: 월말 기준 이용 가능한 최신 (year, reprt)."""
    y, m = int(ym[:4]), int(ym[5:7])
    if m >= 11:
        return y, "11014"
    if m >= 8:
        return y, "11012"
    if m >= 5:
        return y, "11013"
    if m >= 4:
        return y - 1, "11011"
    return y - 1, "11014"


def apply_to_monthly_factor(overwrite_earn_mom: bool = False) -> None:
    """
    quarterly_fund YoY → monthly_factor.sales_g1y/op_g1y/ni_g1y/earn_surprise
    + earn_mom (분기 가능 시).
    """
    conn = _connect()
    ensure_quarterly_table(conn)
    ensure_factor_columns(conn)

    qdf = pd.read_sql(
        """
        SELECT ticker, bsns_year, reprt_code, revenue, op_income, net_income
        FROM quarterly_fund
        """,
        conn,
    )
    if qdf.empty:
        print("⚠️ quarterly_fund 비어 있음 — fetch/import 먼저", flush=True)
        conn.close()
        return

    for c in ("revenue", "op_income", "net_income"):
        qdf[c] = pd.to_numeric(qdf[c], errors="coerce")

    # key: (ticker, year, reprt) → row
    idx = {
        (r.ticker, int(r.bsns_year), r.reprt_code): r
        for r in qdf.itertuples(index=False)
    }

    months = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT date FROM monthly_factor ORDER BY date"
        ).fetchall()
    ]
    print(f"🧮 monthly_factor 적용 | months={len(months)}", flush=True)

    updates = []
    for ym in months:
        year, reprt = latest_reprt_asof(ym)
        prev_year = year - 1
        # 해당 월 종목
        tickers = [
            r[0]
            for r in conn.execute(
                "SELECT ticker FROM monthly_factor WHERE date=?", (ym,)
            ).fetchall()
        ]
        for ticker in tickers:
            cur = idx.get((ticker, year, reprt))
            prev = idx.get((ticker, prev_year, reprt))
            if cur is None or prev is None:
                continue
            sales = _safe_yoy(cur.revenue, prev.revenue)
            op = _safe_yoy(cur.op_income, prev.op_income)
            ni = _safe_yoy(cur.net_income, prev.net_income)
            if sales is None and op is None and ni is None:
                continue
            vals = [v for v in (op, ni) if v is not None]
            earn_mom = float(np.mean(vals)) if vals else None
            # surprise: 컨센서스 없음 → NI YoY 를 실적 서프라이즈 근사
            surprise = ni
            updates.append(
                (sales, op, ni, surprise, earn_mom, ym, ticker)
            )

    if not updates:
        print("⚠️ 적용할 YoY 행 없음 (전년 동일 보고서 부족)", flush=True)
        conn.close()
        return

    conn.executemany(
        """
        UPDATE monthly_factor
        SET sales_g1y=?, op_g1y=?, ni_g1y=?, earn_surprise=?
        WHERE date=? AND ticker=?
        """,
        [
            (s, o, n, sur, ym, t)
            for (s, o, n, sur, _em, ym, t) in updates
        ],
    )

    if overwrite_earn_mom:
        conn.executemany(
            """
            UPDATE monthly_factor
            SET earn_mom=?
            WHERE date=? AND ticker=? AND ? IS NOT NULL
            """,
            [(_em, ym, t, _em) for (_s, _o, _n, _sur, _em, ym, t) in updates],
        )
    else:
        conn.executemany(
            """
            UPDATE monthly_factor
            SET earn_mom=?
            WHERE date=? AND ticker=? AND earn_mom IS NULL AND ? IS NOT NULL
            """,
            [(_em, ym, t, _em) for (_s, _o, _n, _sur, _em, ym, t) in updates],
        )
    conn.commit()
    nn = conn.execute(
        "SELECT SUM(sales_g1y IS NOT NULL), SUM(earn_surprise IS NOT NULL) FROM monthly_factor"
    ).fetchone()
    conn.close()
    print(
        f"✅ 적용 {len(updates)}행 | sales_g1y non-null≈{nn[0]} surprise≈{nn[1]}",
        flush=True,
    )


def main():
    p = argparse.ArgumentParser(description="Phase C9 DART quarterly panel")
    p.add_argument("--import-annual-cache", action="store_true")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--years", type=int, default=2, help="최근 N개 사업연도")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--with-all", action="store_true", help="CF 포함 finstate_all")
    p.add_argument("--overwrite-earn-mom", action="store_true")
    p.add_argument(
        "--reprts",
        default="11013,11012,11014,11011",
        help="쉼표구분 reprt_code",
    )
    args = p.parse_args()

    if args.all:
        args.import_annual_cache = True
        args.fetch = True
        args.apply = True

    if not (args.import_annual_cache or args.fetch or args.apply):
        p.print_help()
        return

    ensure_quarterly_table()
    ensure_factor_columns()

    if args.import_annual_cache:
        import_annual_cache()

    if args.fetch:
        from datetime import datetime

        y_now = datetime.now().year
        # YoY용 직전년 포함: years=2 & 2026 → 2024,2025,2026
        end = y_now
        start = end - args.years + 1
        years = list(range(start - 1, end + 1))
        reprts = tuple(x.strip() for x in args.reprts.split(",") if x.strip())
        fetch_panel(
            years=years,
            limit=args.limit,
            sleep_sec=args.sleep,
            with_all=args.with_all,
            reprts=reprts,
        )

    if args.apply:
        apply_to_monthly_factor(overwrite_earn_mom=args.overwrite_earn_mom)


if __name__ == "__main__":
    main()
