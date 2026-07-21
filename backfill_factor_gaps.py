# -*- coding: utf-8 -*-
"""
결측 팩터 일괄 채우기
1) GPM/F-Score가 빈약한 월 → QuantKing 최신 파일로 월 전체 재적재
2) 그 외 월 → earn_mom(및 결측 GPM/F-Score)만 UPDATE
3) 전체 factor_mom 산출 후 DB 저장
"""
from __future__ import annotations

import glob
import os
import sqlite3
import time

import pandas as pd

from factor_builder import ensure_factor_columns
from momentum_engine import attach_factor_momentum
from raw_data_etl import extract_target_month, map_factor_columns, read_quant_table

DB_PATH = os.path.abspath("./data_cache/quant_history.db")
RAW_DIR = os.path.abspath("./quant_raw_data")


def _nullify(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return v


def latest_file_per_month(min_month: str = "2019-06") -> dict[str, str]:
    """월별 '데이터 기준일'이 가장 최신인 파일 선택 (다운로드 mtime이 아님)."""
    import re

    files = glob.glob(os.path.join(RAW_DIR, "*.xlsx")) + glob.glob(
        os.path.join(RAW_DIR, "*.csv")
    )
    best: dict[str, tuple[str, str]] = {}  # month -> (yyyymmdd or mtime key, path)
    for path in files:
        name = os.path.basename(path)
        if name.startswith("~$"):
            continue
        try:
            month = extract_target_month(name, path)
        except Exception:
            continue
        if not month or month < min_month:
            continue
        # 파일명 2026.07.16 우선
        dm = re.search(r"(20\d{2})\.(\d{2})\.(\d{2})", name)
        if dm:
            key = f"{dm.group(1)}{dm.group(2)}{dm.group(3)}"
        else:
            # 접두 260716... 형태
            pm = re.match(r"^(20\d{2}|[0-9]{2})(\d{2})(\d{2})", name)
            if pm:
                y = pm.group(1)
                if len(y) == 2:
                    y = "20" + y
                key = f"{y}{pm.group(2)}{pm.group(3)}"
            else:
                key = time.strftime("%Y%m%d", time.localtime(os.path.getmtime(path)))
        if month not in best or key >= best[month][0]:
            best[month] = (key, path)
    return {m: p for m, (_, p) in sorted(best.items())}


def load_mapped(path: str) -> pd.DataFrame:
    df = map_factor_columns(read_quant_table(path)).copy()
    if "ticker" not in df.columns:
        return pd.DataFrame()
    t = df["ticker"].astype(str).str.strip()
    digits = (
        t.str.replace(r"^A", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(6)
        .str[-6:]
    )
    df["ticker"] = "A" + digits
    df = df[df["ticker"].str.match(r"^A\d{6}$", na=False)].copy()
    df = df.drop_duplicates(subset=["ticker"], keep="last")
    for col in [
        "per", "pbr", "psr", "ev_ebitda", "roe", "op_margin", "gross_margin",
        "debt_ratio", "f_score", "mom_1m", "mom_6m", "mom_12m", "earn_mom",
    ]:
        if col not in df.columns:
            df[col] = float("nan")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if col in ("per", "pbr", "psr", "ev_ebitda"):
                df.loc[df[col] <= 0, col] = float("nan")
            if col in ("mom_1m", "mom_6m", "mom_12m"):
                df.loc[df[col] <= -99.9, col] = float("nan")
    return df


def full_replace_month(conn: sqlite3.Connection, month: str, df: pd.DataFrame) -> int:
    df = df.copy()
    df["date"] = month
    cols = [
        "date", "ticker", "per", "pbr", "psr", "ev_ebitda", "roe", "op_margin",
        "gross_margin", "debt_ratio", "f_score", "mom_1m", "mom_6m", "mom_12m",
        "earn_mom",
    ]
    rows = [
        tuple(_nullify(v) for v in vals)
        for vals in df[cols].itertuples(index=False, name=None)
    ]
    cur = conn.cursor()
    cur.execute("DELETE FROM monthly_factor WHERE date = ?", (month,))
    cur.executemany(
        """
        INSERT INTO monthly_factor
        (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin,
         debt_ratio, f_score, mom_1m, mom_6m, mom_12m, earn_mom)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def patch_earn_and_quality(conn: sqlite3.Connection, month: str, df: pd.DataFrame) -> int:
    """earn_mom 채우고, GPM/F-Score가 NULL인 행만 보강."""
    rows = [
        (
            _nullify(getattr(r, "earn_mom", None)),
            _nullify(getattr(r, "gross_margin", None)),
            _nullify(getattr(r, "f_score", None)),
            month,
            r.ticker,
        )
        for r in df.itertuples(index=False)
    ]
    cur = conn.cursor()
    cur.executemany(
        """
        UPDATE monthly_factor SET
          earn_mom = COALESCE(?, earn_mom),
          gross_margin = CASE WHEN gross_margin IS NULL THEN ? ELSE gross_margin END,
          f_score = CASE WHEN f_score IS NULL THEN ? ELSE f_score END
        WHERE date = ? AND ticker = ?
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def month_needs_full_reload(conn: sqlite3.Connection, month: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*) n,
               sum(CASE WHEN gross_margin IS NOT NULL THEN 1 ELSE 0 END) g,
               sum(CASE WHEN f_score IS NOT NULL THEN 1 ELSE 0 END) f
        FROM monthly_factor WHERE date=?
        """,
        (month,),
    ).fetchone()
    n, g, f = row[0] or 0, row[1] or 0, row[2] or 0
    if n == 0:
        return True
    # 커버리지 30% 미만이면 깨진 월로 판단
    return (g / n < 0.3) or (f / n < 0.3)


def clean_garbage_rows(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM monthly_factor
        WHERE ticker NOT GLOB 'A[0-9][0-9][0-9][0-9][0-9][0-9]'
        """
    )
    n = cur.rowcount
    conn.commit()
    return n


def update_factor_mom(conn: sqlite3.Connection) -> int:
    df = pd.read_sql(
        """
        SELECT date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin,
               gross_margin, f_score, mom_1m, mom_6m, mom_12m, earn_mom
        FROM monthly_factor
        """,
        conn,
    )
    print(f"  factor_mom 계산 중... ({len(df):,}행, 수 분 소요 가능)")
    out = attach_factor_momentum(df, lookback=6)
    upd = out[["date", "ticker", "factor_mom"]].dropna(subset=["factor_mom"])
    cur = conn.cursor()
    cur.executemany(
        """
        UPDATE monthly_factor
        SET factor_mom = ?
        WHERE date = ? AND ticker = ?
        """,
        [(float(r.factor_mom), r.date, r.ticker) for r in upd.itertuples(index=False)],
    )
    conn.commit()
    return len(upd)


def coverage(conn: sqlite3.Connection, month: str | None = None) -> pd.DataFrame:
    if month:
        return pd.read_sql(
            """
            SELECT count(*) n,
                   sum(gross_margin IS NOT NULL) gpm,
                   sum(f_score IS NOT NULL) fs,
                   sum(earn_mom IS NOT NULL) em,
                   sum(factor_mom IS NOT NULL) fm
            FROM monthly_factor WHERE date=?
            """,
            conn,
            params=(month,),
        )
    return pd.read_sql(
        """
        SELECT count(*) n,
               sum(gross_margin IS NOT NULL) gpm,
               sum(f_score IS NOT NULL) fs,
               sum(earn_mom IS NOT NULL) em,
               sum(factor_mom IS NOT NULL) fm
        FROM monthly_factor
        """,
        conn,
    )


def main():
    t0 = time.time()
    print("=" * 60)
    print("🩹 결측 팩터 일괄 백필")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH, timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=600000")
    ensure_factor_columns(conn)
    conn.commit()

    print("\n[0] 백필 전")
    print(coverage(conn).to_string(index=False))
    print("2026-07", coverage(conn, "2026-07").to_string(index=False))

    print(f"\n[1] 쓰레기 티커 삭제: {clean_garbage_rows(conn)}행")

    month_files = latest_file_per_month("2019-06")
    # 최근 월 우선
    months = sorted(month_files.keys(), reverse=True)
    print(f"\n[2] QuantKing 백필 대상: {len(months)}개월")

    for i, month in enumerate(months, 1):
        path = month_files[month]
        try:
            df = load_mapped(path)
            if df.empty:
                print(f"  [{i}/{len(months)}] {month} 스킵(빈 DF)")
                continue
            if month_needs_full_reload(conn, month):
                n = full_replace_month(conn, month, df)
                mode = "FULL"
            else:
                n = patch_earn_and_quality(conn, month, df)
                mode = "PATCH"
            em = conn.execute(
                "SELECT sum(earn_mom IS NOT NULL) FROM monthly_factor WHERE date=?",
                (month,),
            ).fetchone()[0]
            print(
                f"  [{i}/{len(months)}] {month} {mode}: touch={n:,} earn_mom={em} | {os.path.basename(path)[:42]}"
            )
        except Exception as e:
            print(f"  [{i}/{len(months)}] {month} 실패: {e}")

    print("\n[3] factor_mom 전체 갱신")
    n_fm = update_factor_mom(conn)
    print(f"  UPDATE {n_fm:,}행")

    print("\n[4] 백필 후")
    print(coverage(conn).to_string(index=False))
    print("2026-07", coverage(conn, "2026-07").to_string(index=False))
    conn.close()
    print(f"\n✅ 완료 {time.time() - t0:.1f}초")
    print("👉 Streamlit 재시작 또는 캐시 초기화 후 확인하세요.")


if __name__ == "__main__":
    main()
