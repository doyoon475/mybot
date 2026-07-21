"""
일일 퀀트 데이터 누적 파이프라인.

1) 퀀트킹 최신 게시물 첨부 수집 (API)
2) raw → monthly_factor ETL (최근 파일만)
3) daily_price 증분 갱신 (FinanceDataReader)

로컬:  python daily_updater.py
CI:    GitHub Actions (.github/workflows/daily_update.yml)
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

# Windows 콘솔 한글
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = os.path.abspath("./data_cache/quant_history.db")


def _checkpoint_db():
    """WAL을 본 DB에 합쳐 Release/캐시 업로드 시 누락 방지."""
    if not os.path.exists(DB_PATH):
        return
    try:
        conn = sqlite3.connect(DB_PATH, timeout=60)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception as e:
        print(f"⚠️ WAL checkpoint 경고: {e}")


def _print_db_stats():
    if not os.path.exists(DB_PATH):
        print("⚠️ DB 파일 없음:", DB_PATH)
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        mf = conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM monthly_factor"
        ).fetchone()
        dp = conn.execute(
            "SELECT MIN(date), MAX(date), COUNT(*) FROM daily_price"
        ).fetchone()
        print(f"📊 monthly_factor: {mf[0]} ~ {mf[1]} ({mf[2]}개월)")
        print(f"📊 daily_price:    {dp[0]} ~ {dp[1]} ({dp[2]:,}행)")
        print(f"📦 DB 크기: {os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB")
    finally:
        conn.close()


def run_quantking_fetch(pages: int = 2) -> dict:
    print("\n[1/3] 퀀트킹 최신 첨부 수집")
    from quantking_client import fetch_latest_quant_files

    return fetch_latest_quant_files(dest_dir="./quant_raw_data", pages=pages)


def run_factor_etl(only_recent_files: int = 40):
    print("\n[2/3] 팩터 ETL (최근 파일)")
    from raw_data_etl import process_raw_data

    # 같은 월은 INSERT OR REPLACE 로 최신 일자 스냅샷으로 덮어씀
    process_raw_data(skip_existing_months=False, only_recent_files=only_recent_files)


def run_price_update(lookback_days: int = 14):
    print("\n[3/3] 주가 증분 갱신")
    from price_etl import update_prices_incremental

    update_prices_incremental(lookback_days=lookback_days)


def run_daily_pipeline(
    quant_pages: int = 2,
    price_lookback_days: int = 14,
    etl_recent_files: int = 40,
    skip_quantking: bool = False,
    skip_price: bool = False,
):
    print("=" * 60)
    print(f"🤖 일일 데이터 파이프라인 | {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 60)
    t0 = time.time()
    errors = []

    if not skip_quantking:
        try:
            run_quantking_fetch(pages=quant_pages)
        except Exception as e:
            errors.append(f"quantking: {e}")
            print(f"🚨 퀀트킹 수집 실패 (이어서 진행): {e}")

    try:
        run_factor_etl(only_recent_files=etl_recent_files)
    except Exception as e:
        errors.append(f"etl: {e}")
        print(f"🚨 ETL 실패: {e}")

    if not skip_price:
        try:
            run_price_update(lookback_days=price_lookback_days)
        except Exception as e:
            errors.append(f"price: {e}")
            print(f"🚨 주가 갱신 실패: {e}")

    _checkpoint_db()
    print("-" * 60)
    _print_db_stats()
    print("=" * 60)
    if errors:
        print(f"⚠️ 부분 실패 ({time.time() - t0:.1f}초): {errors}")
        sys.exit(1)
    print(f"🎉 일일 업데이트 완료 ({time.time() - t0:.1f}초)")


if __name__ == "__main__":
    skip_qk = os.getenv("SKIP_QUANTKING", "").lower() in ("1", "true", "yes")
    skip_px = os.getenv("SKIP_PRICE", "").lower() in ("1", "true", "yes")
    pages = int(os.getenv("QUANTKING_PAGES", "2"))
    lookback = int(os.getenv("PRICE_LOOKBACK_DAYS", "14"))
    run_daily_pipeline(
        quant_pages=pages,
        price_lookback_days=lookback,
        skip_quantking=skip_qk,
        skip_price=skip_px,
    )
