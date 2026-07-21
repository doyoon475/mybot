import os
import sqlite3
import time
from datetime import datetime, timedelta

import pandas as pd
import FinanceDataReader as fdr

DB_PATH = os.path.abspath("./data_cache/quant_history.db")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=120)
    cur = conn.cursor()
    cur.execute("PRAGMA synchronous = NORMAL")
    cur.execute("PRAGMA journal_mode = WAL")
    cur.execute("PRAGMA busy_timeout = 120000")
    return conn


def build_price_pipeline(start_date: str = "2016-01-01"):
    print("🚀 [주가 적재 파이프라인] 일별 주가 고속 적재를 시작합니다...")
    start_time = time.time()

    conn = _connect()
    cursor = conn.cursor()

    df_master = pd.read_sql("SELECT ticker FROM stock_master WHERE is_active = 1", conn)
    tickers = df_master["ticker"].tolist()
    print(f"📊 총 {len(tickers)}개 종목 | 시작일 {start_date}")

    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] {ticker} 주가 수집 중...", end="\r")
        try:
            fdr_ticker = ticker[1:] if ticker.startswith("A") else ticker
            df_price = fdr.DataReader(fdr_ticker, start_date)
            if df_price is None or df_price.empty:
                continue

            df_price = df_price.reset_index()
            date_col = "Date" if "Date" in df_price.columns else df_price.columns[0]
            vol = (
                df_price["Volume"]
                if "Volume" in df_price.columns
                else pd.Series([0] * len(df_price))
            )
            price_data = list(
                zip(
                    pd.to_datetime(df_price[date_col]).dt.strftime("%Y-%m-%d"),
                    [ticker] * len(df_price),
                    df_price["Close"],
                    vol,
                )
            )
            cursor.executemany(
                """
                INSERT OR REPLACE INTO daily_price (date, ticker, close, volume)
                VALUES (?, ?, ?, ?)
                """,
                price_data,
            )
            if (i + 1) % 50 == 0:
                conn.commit()
                time.sleep(0.2)
        except Exception:
            continue

    conn.commit()
    conn.close()
    print(f"\n✅ [성공] 주가 적재 완료 | {time.time() - start_time:.1f}초")


def update_prices_incremental(lookback_days: int = 14):
    """일일 자동화용 증분 갱신."""
    conn = _connect()
    try:
        row = conn.execute("SELECT MAX(date) FROM daily_price").fetchone()
        max_date = row[0] if row and row[0] else None
    finally:
        conn.close()

    if max_date:
        start = (
            datetime.strptime(max_date, "%Y-%m-%d") - timedelta(days=lookback_days)
        ).strftime("%Y-%m-%d")
    else:
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    print(f"📈 [증분 주가] {start} ~ 오늘 (lookback={lookback_days}일)")
    build_price_pipeline(start_date=start)


if __name__ == "__main__":
    update_prices_incremental()
