"""
자체 팩터 공장: DART 재무 + KRX/일봉 주가 → monthly_factor 월말 스냅샷

퀀트킹 구독 종료 후에도 동일한 monthly_factor 스키마로 데이터를 누적한다.
1차 목표: 모멘텀(완전) + 기본 멀티플/수익성(DART) 를 안정적으로 적재.
EV/EBITDA·F-Score 는 가능한 범위에서 근사치(없으면 NULL).

사용 예:
  python factor_builder.py                  # 이번 달 전체(시간 오래 걸림)
  python factor_builder.py --limit 20       # 스모크 테스트
  python factor_builder.py --month 2026-07  # 특정 월
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = os.path.abspath("./data_cache/quant_history.db")
DART_CACHE_DIR = os.path.abspath("./data_cache/dart_cache")

# DART 계정명 → 내부 키 (부분 일치)
ACCOUNT_ALIASES = {
    "revenue": ["매출액", "수익(매출액)", "영업수익", "매출"],
    "op_income": ["영업이익"],
    "net_income": [
        "당기순이익",
        "당기순이익(손실)",
        "지배기업의 소유주에게 귀속되는 당기순이익",
        "지배주주순이익",
    ],
    "equity": ["자본총계", "자본금"],
    "assets": ["자산총계"],
    "liabilities": ["부채총계"],
    "gross_profit": ["매출총이익", "매출총이익(손실)"],
    "ebitda": ["EBITDA", "ebitda"],
}


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=120000")
    return conn


def _norm_ticker(t: str) -> str:
    s = str(t).strip().upper()
    if s.startswith("A") and len(s) >= 7:
        return "A" + re.sub(r"\D", "", s[1:])[-6:].zfill(6)
    digits = re.sub(r"\D", "", s)[-6:].zfill(6)
    return "A" + digits


def _dart_code(ticker: str) -> str:
    return _norm_ticker(ticker)[1:]


def _to_float(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        s = str(v).replace(",", "").strip()
        if s in ("", "-", "nan", "None"):
            return None
        return float(s)
    except Exception:
        return None


def _pick_account(df: pd.DataFrame, keys: List[str]) -> Optional[float]:
    if df is None or df.empty or "account_nm" not in df.columns:
        return None
    # 연결 우선
    work = df
    if "fs_div" in df.columns:
        cons = df[df["fs_div"].astype(str).str.upper().isin(["CFS", "연결"])]
        if not cons.empty:
            work = cons
    names = work["account_nm"].astype(str)
    for key in keys:
        hit = work[names == key]
        if hit.empty:
            hit = work[names.str.contains(re.escape(key), na=False)]
        if hit.empty:
            continue
        for col in ("thstrm_amount", "thstrm_add_amount", "thstrm"):
            if col in hit.columns:
                val = _to_float(hit.iloc[0][col])
                if val is not None:
                    return val
    return None


def _init_dart():
    try:
        import OpenDartReader
    except ImportError:
        print("❌ OpenDartReader 미설치: pip install OpenDartReader")
        return None
    key = os.getenv("DART_API_KEY")
    if not key:
        print("❌ DART_API_KEY 없음 (.env 또는 GitHub Secrets)")
        return None
    try:
        return OpenDartReader(key)
    except Exception as e:
        print(f"❌ DART 초기화 실패: {e}")
        return None


def _cache_path(ticker: str, year: int) -> str:
    os.makedirs(DART_CACHE_DIR, exist_ok=True)
    return os.path.join(DART_CACHE_DIR, f"{_dart_code(ticker)}_{year}.parquet")


def fetch_finstate_cached(dart, ticker: str, year: int, sleep_sec: float = 1.0) -> pd.DataFrame:
    path = _cache_path(ticker, year)
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    if dart is None:
        return pd.DataFrame()

    time.sleep(max(0.3, sleep_sec))  # rate limit
    code = _dart_code(ticker)
    try:
        # 사업보고서 → 없으면 3분기/반기 순으로 시도
        for reprt in ("11011", "11014", "11012", "11013"):
            try:
                df = dart.finstate(corp=code, bsns_year=year, reprt_code=reprt)
            except TypeError:
                # OpenDartReader가 빈 응답(None)을 내부에서 순회하다 터지는 경우
                continue
            except Exception:
                continue
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                continue
            try:
                df.to_parquet(path, index=False)
            except Exception:
                pass
            return df
    except Exception as e:
        # 개별 종목 실패는 전체 중단 사유가 아님
        msg = str(e)
        if "NoneType" not in msg:
            print(f"  ⚠️ DART {code}: {msg[:80]}")
    return pd.DataFrame()


def extract_fundamentals(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    out = {k: _pick_account(df, aliases) for k, aliases in ACCOUNT_ALIASES.items()}
    # 자본총계가 자본금만 잡히는 경우 방지: 자본총계 재탐색
    if out.get("equity") is not None and out["equity"] < 1e9:
        eq2 = _pick_account(df, ["자본총계"])
        if eq2 is not None:
            out["equity"] = eq2
    return out


def load_listings_marcap() -> pd.DataFrame:
    """시가총액·상장주식수 (현재 기준, FDR)."""
    import FinanceDataReader as fdr

    frames = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = fdr.StockListing(market)
            if df is None or df.empty:
                continue
            df = df.copy()
            df["market"] = market
            frames.append(df)
            time.sleep(0.5)
        except Exception as e:
            print(f"⚠️ StockListing {market} 실패: {e}")
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    code_col = "Code" if "Code" in raw.columns else raw.columns[0]
    raw["ticker"] = raw[code_col].map(_norm_ticker)
    # Marcap 단위: FDR은 원 단위
    keep = {"ticker": raw["ticker"]}
    if "Marcap" in raw.columns:
        keep["marcap"] = pd.to_numeric(raw["Marcap"], errors="coerce")
    if "Stocks" in raw.columns:
        keep["stocks"] = pd.to_numeric(raw["Stocks"], errors="coerce")
    if "Close" in raw.columns:
        keep["list_close"] = pd.to_numeric(raw["Close"], errors="coerce")
    out = pd.DataFrame(keep).dropna(subset=["ticker"]).drop_duplicates("ticker")
    return out


def month_end_closes(conn: sqlite3.Connection, target_month: str) -> pd.DataFrame:
    """target_month(YYYY-MM) 이전 포함 최근 종가."""
    # 해당 월 마지막 거래일 종가
    q = """
        SELECT p.ticker, p.date, p.close
        FROM daily_price p
        INNER JOIN (
            SELECT ticker, MAX(date) AS max_date
            FROM daily_price
            WHERE date <= ?
            GROUP BY ticker
        ) t ON p.ticker = t.ticker AND p.date = t.max_date
    """
    # 월말 날짜 상한: YYYY-MM-31
    asof = f"{target_month}-31"
    df = pd.read_sql(q, conn, params=(asof,))
    return df


def compute_momentum(conn: sqlite3.Connection, target_month: str) -> pd.DataFrame:
    """
    mom_Xm = (P_t / P_t-X) - 1 을 %로.
    """
    asof = f"{target_month}-31"
    # 필요 구간: 약 280거래일 ≈ 13개월
    q = """
        SELECT ticker, date, close
        FROM daily_price
        WHERE date <= ?
          AND date >= date(?, '-400 days')
        ORDER BY ticker, date
    """
    px = pd.read_sql(q, conn, params=(asof, asof))
    if px.empty:
        return pd.DataFrame(columns=["ticker", "close", "mom_1m", "mom_6m", "mom_12m", "asof_date"])

    px["date"] = pd.to_datetime(px["date"])
    rows = []
    for ticker, g in px.groupby("ticker"):
        g = g.sort_values("date")
        if g.empty:
            continue
        last = g.iloc[-1]
        p0 = float(last["close"])
        d0 = last["date"]

        def ret(days: int) -> Optional[float]:
            target = d0 - pd.Timedelta(days=days)
            past = g[g["date"] <= target]
            if past.empty or p0 == 0:
                return None
            p1 = float(past.iloc[-1]["close"])
            if p1 == 0:
                return None
            return (p0 / p1 - 1.0) * 100.0

        rows.append(
            {
                "ticker": ticker,
                "close": p0,
                "asof_date": d0.strftime("%Y-%m-%d"),
                "mom_1m": ret(30),
                "mom_6m": ret(182),
                "mom_12m": ret(365),
            }
        )
    return pd.DataFrame(rows)


def safe_div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def build_row(
    ticker: str,
    target_month: str,
    mom: dict,
    fund: Dict[str, Optional[float]],
    marcap: Optional[float],
) -> Dict[str, Any]:
    ni = fund.get("net_income")
    eq = fund.get("equity")
    rev = fund.get("revenue")
    op = fund.get("op_income")
    gp = fund.get("gross_profit")
    liab = fund.get("liabilities")
    ebitda = fund.get("ebitda")

    # PER: 적자이면 None (랭킹에서 불리하게 두려면 대시보드에서 처리)
    per = safe_div(marcap, ni) if (ni is not None and ni > 0 and marcap) else None
    pbr = safe_div(marcap, eq) if (eq is not None and eq > 0 and marcap) else None
    psr = safe_div(marcap, rev) if (rev is not None and rev > 0 and marcap) else None
    # EV/EBITDA 근사: EV≈시총+순부채 ≈ 시총+부채-현금(현금 없으면 시총+부채)
    # 1차: marcap / ebitda (조악) 또는 None
    ev_ebitda = None
    if ebitda and ebitda > 0 and marcap:
        ev_ebitda = marcap / ebitda
    elif op and op > 0 and marcap:
        # 감가삼각 없이 영업이익으로 임시 근사 (표시용, 추후 개선)
        ev_ebitda = marcap / op

    roe = safe_div(ni, eq) * 100.0 if (ni is not None and eq) else None
    op_margin = safe_div(op, rev) * 100.0 if (op is not None and rev) else None
    gross_margin = safe_div(gp, rev) * 100.0 if (gp is not None and rev) else None
    debt_ratio = safe_div(liab, eq) * 100.0 if (liab is not None and eq) else None

    return {
        "date": target_month,
        "ticker": ticker,
        "per": per,
        "pbr": pbr,
        "psr": psr,
        "ev_ebitda": ev_ebitda,
        "roe": roe,
        "op_margin": op_margin,
        "gross_margin": gross_margin,
        "debt_ratio": debt_ratio,
        "f_score": None,  # 2차 구현
        "mom_1m": mom.get("mom_1m"),
        "mom_6m": mom.get("mom_6m"),
        "mom_12m": mom.get("mom_12m"),
    }


def upsert_factors(rows: List[dict]):
    if not rows:
        print("⚠️ 적재할 행 없음")
        return
    conn = _connect()
    cur = conn.cursor()
    data = [
        (
            r["date"],
            r["ticker"],
            r.get("per"),
            r.get("pbr"),
            r.get("psr"),
            r.get("ev_ebitda"),
            r.get("roe"),
            r.get("op_margin"),
            r.get("gross_margin"),
            r.get("debt_ratio"),
            r.get("f_score"),
            r.get("mom_1m"),
            r.get("mom_6m"),
            r.get("mom_12m"),
        )
        for r in rows
    ]
    cur.executemany(
        """
        INSERT OR REPLACE INTO monthly_factor
        (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin,
         debt_ratio, f_score, mom_1m, mom_6m, mom_12m)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        data,
    )
    conn.commit()
    conn.close()
    print(f"✅ monthly_factor 적재: {len(data):,}행 ({rows[0]['date']})")


def build_monthly_factors(
    target_month: Optional[str] = None,
    limit: Optional[int] = None,
    sleep_sec: float = 1.0,
    skip_dart: bool = False,
) -> pd.DataFrame:
    target_month = target_month or datetime.now().strftime("%Y-%m")
    print("=" * 60)
    print(f"🏭 자체 팩터 빌드 | 대상월 {target_month}")
    print("=" * 60)

    conn = _connect()
    tickers = pd.read_sql(
        "SELECT ticker FROM stock_master WHERE is_active = 1 ORDER BY ticker",
        conn,
    )["ticker"].map(_norm_ticker).tolist()
    if limit:
        tickers = tickers[:limit]
        print(f"🔬 테스트 모드: {len(tickers)}종목만")

    print("📈 모멘텀 계산 중...")
    mom_df = compute_momentum(conn, target_month)
    mom_map = mom_df.set_index("ticker").to_dict("index") if not mom_df.empty else {}
    print(f"  모멘텀 확보: {len(mom_map)}종목")

    print("💹 시가총액(FDR Listing) 로드...")
    listing = load_listings_marcap()
    marcap_map = {}
    if not listing.empty and "marcap" in listing.columns:
        marcap_map = listing.set_index("ticker")["marcap"].to_dict()
    print(f"  시총 확보: {len(marcap_map)}종목")

    dart = None if skip_dart else _init_dart()
    year = int(target_month[:4])
    # 연초면 전년 사업보고서가 더 안정적
    fin_year = year - 1 if int(target_month[5:7]) <= 3 else year - 1
    # 통상 직전 확정 연간: 작년
    fin_year = datetime.now().year - 1

    rows = []
    ok_fund = 0
    for i, ticker in enumerate(tickers, 1):
        mom = mom_map.get(ticker, {})
        fund: Dict[str, Optional[float]] = {k: None for k in ACCOUNT_ALIASES}
        if dart is not None:
            df_fin = fetch_finstate_cached(dart, ticker, fin_year, sleep_sec=sleep_sec)
            if not df_fin.empty:
                fund = extract_fundamentals(df_fin)
                if any(v is not None for v in fund.values()):
                    ok_fund += 1

        marcap = marcap_map.get(ticker)
        # 시총 없으면 종가×상장주식수 근사
        if marcap is None and not listing.empty and mom.get("close"):
            hit = listing[listing["ticker"] == ticker]
            if not hit.empty and "stocks" in hit.columns:
                stocks = _to_float(hit.iloc[0].get("stocks"))
                if stocks:
                    marcap = float(mom["close"]) * stocks

        rows.append(build_row(ticker, target_month, mom, fund, marcap))
        if i % 50 == 0 or i == len(tickers):
            print(f"  [{i}/{len(tickers)}] 진행 | DART재무 성공누적 {ok_fund}")

    conn.close()
    out = pd.DataFrame(rows)
    upsert_factors(rows)
    print(f"📊 DART 재무 매핑 성공: {ok_fund}/{len(tickers)}")
    print(f"📊 모멘텀 비어있지 않은 종목: {out['mom_12m'].notna().sum()}")
    return out


def main():
    p = argparse.ArgumentParser(description="DART+주가 → monthly_factor 자체 생성")
    p.add_argument("--month", type=str, default=None, help="YYYY-MM")
    p.add_argument("--limit", type=int, default=None, help="종목 수 제한(테스트)")
    p.add_argument("--sleep", type=float, default=1.0, help="DART 호출 간격(초)")
    p.add_argument("--skip-dart", action="store_true", help="모멘텀만 갱신")
    args = p.parse_args()
    build_monthly_factors(
        target_month=args.month,
        limit=args.limit,
        sleep_sec=args.sleep,
        skip_dart=args.skip_dart,
    )


if __name__ == "__main__":
    main()
