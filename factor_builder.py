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
    "equity": ["자본총계"],
    "assets": ["자산총계"],
    "liabilities": ["부채총계"],
    # gross_profit 등 나머지는 아래에서 병합
    "gross_profit": [
        "매출총이익",
        "매출총이익(손실)",
        "매출 총이익",
        "영업총이익",
        "매출총이익 금액",
    ],
    "ebitda": ["EBITDA", "ebitda"],
    "cfo": [
        "영업활동현금흐름",
        "영업활동으로인한현금흐름",
        "영업활동으로 인한 현금흐름",
        "영업활동으로 인한 현금흐름(간접법)",
    ],
    "capex": [
        "유형자산의 취득",
        "유형자산의취득",
        "유형자산의 취득으로 인한 현금유출",
        "기계장치의 취득",
        "건설중인자산의 취득",
    ],
}


FINANCIAL_SECTOR_KEYWORDS = ("금융", "은행", "보험", "증권", "카드", "캐피탈", "저축")


def is_financial_sector(sector: Optional[str]) -> bool:
    s = str(sector or "")
    return any(k in s for k in FINANCIAL_SECTOR_KEYWORDS)


def ensure_factor_columns(conn: Optional[sqlite3.Connection] = None) -> None:
    """신규 팩터 컬럼을 기존 DB에 안전하게 추가."""
    own = conn is None
    if own:
        conn = _connect()
    try:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(monthly_factor)")}
        for col, typ in (
            ("earn_mom", "REAL"),
            ("factor_mom", "REAL"),
            ("accrual", "REAL"),
            ("fcf_yield", "REAL"),
            ("vol_12m", "REAL"),
        ):
            if col not in existing:
                conn.execute(f"ALTER TABLE monthly_factor ADD COLUMN {col} {typ}")
                print(f"  ➕ monthly_factor.{col} 컬럼 추가")
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


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


def _cache_path_all(ticker: str, year: int) -> str:
    os.makedirs(DART_CACHE_DIR, exist_ok=True)
    return os.path.join(DART_CACHE_DIR, f"{_dart_code(ticker)}_{year}_all.parquet")


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


def fetch_finstate_all_cached(
    dart,
    ticker: str,
    year: int,
    sleep_sec: float = 1.0,
) -> pd.DataFrame:
    """
    단일회사 전체 재무제표(fnlttSinglAcntAll) — CF(CFO/CapEx) 포함.
    BS/IS 전용 캐시와 분리해 {code}_{year}_all.parquet 로 저장.
    """
    path = _cache_path_all(ticker, year)
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            pass
    if dart is None:
        return pd.DataFrame()

    try:
        from OpenDartReader import dart_finstate
    except Exception:
        try:
            import OpenDartReader.dart_finstate as dart_finstate
        except Exception as e:
            print(f"  ⚠️ dart_finstate import 실패: {e}")
            return pd.DataFrame()

    time.sleep(max(0.3, sleep_sec))
    code = _dart_code(ticker)
    # corp_code 조회 (OpenDartReader 내부 코드)
    corp_code = code
    try:
        if hasattr(dart, "find_corp_code"):
            found = dart.find_corp_code(code)
            if found:
                corp_code = found
    except Exception:
        pass

    for reprt in ("11011", "11014", "11012", "11013"):
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


def _sum_accounts(df: pd.DataFrame, keys: List[str]) -> Optional[float]:
    """CapEx처럼 여러 계정을 합산할 때 사용."""
    if df is None or df.empty or "account_nm" not in df.columns:
        return None
    work = df
    if "fs_div" in df.columns:
        cons = df[df["fs_div"].astype(str).str.upper().isin(["CFS", "연결"])]
        if not cons.empty:
            work = cons
    names = work["account_nm"].astype(str)
    total = 0.0
    found = False
    for key in keys:
        hit = work[names == key]
        if hit.empty:
            hit = work[names.str.contains(re.escape(key), na=False)]
        for _, row in hit.iterrows():
            for col in ("thstrm_amount", "thstrm_add_amount", "thstrm"):
                if col in row.index:
                    val = _to_float(row[col])
                    if val is not None:
                        total += abs(val)  # 유출액은 부호 혼재 → 절대값 합산
                        found = True
                        break
    return total if found else None


def extract_fundamentals(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    out = {k: _pick_account(df, aliases) for k, aliases in ACCOUNT_ALIASES.items()}
    # CapEx: 단일 픽 실패 시 후보 합산
    if out.get("capex") is None:
        out["capex"] = _sum_accounts(df, ACCOUNT_ALIASES["capex"])
    # 자본총계가 자본금만 잡히는 경우 방지: 자본총계 재탐색
    if out.get("equity") is not None and out["equity"] < 1e9:
        eq2 = _pick_account(df, ["자본총계"])
        if eq2 is not None:
            out["equity"] = eq2
    return out


def merge_fundamentals(
    base: Dict[str, Optional[float]],
    extra: Dict[str, Optional[float]],
) -> Dict[str, Optional[float]]:
    """extra의 non-null로 base를 보강 (CFO/CapEx 등)."""
    out = dict(base)
    for k, v in extra.items():
        if v is not None and (out.get(k) is None):
            out[k] = v
        elif v is not None and k in ("cfo", "capex"):
            out[k] = v  # CF는 all 제표 우선
    return out


def compute_accrual(fund: Dict[str, Optional[float]]) -> Optional[float]:
    """(NI − CFO) / Assets × 100. 낮을수록 이익 품질↑."""
    ni = fund.get("net_income")
    cfo = fund.get("cfo")
    assets = fund.get("assets")
    if ni is None or cfo is None or not assets:
        return None
    return (ni - cfo) / assets * 100.0


def compute_fcf_yield(
    fund: Dict[str, Optional[float]],
    marcap: Optional[float],
    financial: bool = False,
) -> Optional[float]:
    """(CFO − |CapEx|) / 시총 × 100. 금융주는 NULL."""
    if financial:
        return None
    cfo = fund.get("cfo")
    if cfo is None or not marcap or marcap <= 0:
        return None
    capex = fund.get("capex")
    capex_v = abs(capex) if capex is not None else 0.0
    fcf = cfo - capex_v
    return fcf / marcap * 100.0


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


def compute_f_score(
    fund: Dict[str, Optional[float]],
    prev: Optional[Dict[str, Optional[float]]] = None,
) -> Optional[int]:
    """
    Piotroski F-Score 근사 (0~9).
    전년 캐시가 있으면 YoY 항목 포함, 없으면 당기 신호만으로 가능한 점수만 합산.
    계산 불가 시 None (0으로 채우지 않음).
    """
    ni = fund.get("net_income")
    assets = fund.get("assets")
    eq = fund.get("equity")
    rev = fund.get("revenue")
    op = fund.get("op_income")
    gp = fund.get("gross_profit")
    liab = fund.get("liabilities")
    cfo = fund.get("cfo")

    if all(v is None for v in (ni, assets, eq, rev, op, gp, liab, cfo)):
        return None

    score = 0
    # 1) ROA > 0
    if assets and assets > 0 and ni is not None and ni > 0:
        score += 1
    # 2) 영업CF > 0 (없으면 영업이익 > 0 으로 대체)
    if cfo is not None:
        if cfo > 0:
            score += 1
    elif op is not None and op > 0:
        score += 1
    # 3) Accrual: CFO > NI (품질) — CFO 없으면 스킵
    if cfo is not None and ni is not None and cfo > ni:
        score += 1
    elif cfo is None and ni is not None and ni > 0:
        # CFO 없을 때 당기순이익>0으로 약한 대체(기존 호환)
        score += 1
    # 4) 매출총이익률 > 0 (없으면 OPM>0 대체)
    gpm = safe_div(gp, rev)
    if gpm is not None and gpm > 0:
        score += 1
    elif gpm is None:
        opm = safe_div(op, rev)
        if opm is not None and opm > 0:
            score += 1
    # 5) 레버리지(부채/자산) 낮음 근사: < 0.7
    lev = safe_div(liab, assets)
    if lev is not None and lev < 0.7:
        score += 1

    if prev:
        # 6) ROA 개선
        ra = safe_div(ni, assets)
        ra0 = safe_div(prev.get("net_income"), prev.get("assets"))
        if ra is not None and ra0 is not None and ra > ra0:
            score += 1
        # 7) 레버리지 감소
        lev0 = safe_div(prev.get("liabilities"), prev.get("assets"))
        if lev is not None and lev0 is not None and lev < lev0:
            score += 1
        # 8) GPM 개선 (없으면 OPM 개선)
        gpm0 = safe_div(prev.get("gross_profit"), prev.get("revenue"))
        if gpm is not None and gpm0 is not None and gpm > gpm0:
            score += 1
        else:
            opm = safe_div(op, rev)
            opm0 = safe_div(prev.get("op_income"), prev.get("revenue"))
            if opm is not None and opm0 is not None and opm > opm0:
                score += 1
        # 9) 자산회전율 개선 (매출/자산)
        at = safe_div(rev, assets)
        at0 = safe_div(prev.get("revenue"), prev.get("assets"))
        if at is not None and at0 is not None and at > at0:
            score += 1

    return int(min(score, 9))


def build_row(
    ticker: str,
    target_month: str,
    mom: dict,
    fund: Dict[str, Optional[float]],
    marcap: Optional[float],
    prev_fund: Optional[Dict[str, Optional[float]]] = None,
    sector: Optional[str] = None,
) -> Dict[str, Any]:
    from momentum_engine import compute_earn_mom_from_fund

    ni = fund.get("net_income")
    eq = fund.get("equity")
    rev = fund.get("revenue")
    op = fund.get("op_income")
    gp = fund.get("gross_profit")
    liab = fund.get("liabilities")
    ebitda = fund.get("ebitda")

    per = safe_div(marcap, ni) if (ni is not None and ni > 0 and marcap) else None
    pbr = safe_div(marcap, eq) if (eq is not None and eq > 0 and marcap) else None
    psr = safe_div(marcap, rev) if (rev is not None and rev > 0 and marcap) else None
    ev_ebitda = None
    if ebitda and ebitda > 0 and marcap:
        ev_ebitda = marcap / ebitda
    elif op and op > 0 and marcap and liab is not None:
        # EV ≈ 시총 + 부채 (현금 미차감 근사) / 영업이익
        ev_ebitda = (marcap + max(liab, 0)) / op
    elif op and op > 0 and marcap:
        ev_ebitda = marcap / op

    roe = safe_div(ni, eq) * 100.0 if (ni is not None and eq) else None
    op_margin = safe_div(op, rev) * 100.0 if (op is not None and rev) else None
    # GPM: 매출총이익 우선, 없으면 None 유지(OPM으로 위장하지 않음)
    gross_margin = safe_div(gp, rev) * 100.0 if (gp is not None and rev) else None
    debt_ratio = safe_div(liab, eq) * 100.0 if (liab is not None and eq) else None
    f_score = compute_f_score(fund, prev_fund)
    earn_mom = compute_earn_mom_from_fund(fund, prev_fund)
    financial = is_financial_sector(sector)
    accrual = compute_accrual(fund)
    fcf_yield = compute_fcf_yield(fund, marcap, financial=financial)

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
        "f_score": f_score,
        "mom_1m": mom.get("mom_1m"),
        "mom_6m": mom.get("mom_6m"),
        "mom_12m": mom.get("mom_12m"),
        "earn_mom": earn_mom,
        "accrual": accrual,
        "fcf_yield": fcf_yield,
    }


def upsert_factors(rows: List[dict]):
    if not rows:
        print("⚠️ 적재할 행 없음")
        return
    conn = _connect()
    ensure_factor_columns(conn)
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
            r.get("fcf_yield"),
            r.get("mom_1m"),
            r.get("mom_6m"),
            r.get("mom_12m"),
            r.get("earn_mom"),
            r.get("accrual"),
        )
        for r in rows
    ]
    cur.executemany(
        """
        INSERT OR REPLACE INTO monthly_factor
        (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin,
         debt_ratio, f_score, fcf_yield, mom_1m, mom_6m, mom_12m, earn_mom, accrual)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    master = pd.read_sql(
        "SELECT ticker, sector FROM stock_master WHERE is_active = 1 ORDER BY ticker",
        conn,
    )
    master["ticker"] = master["ticker"].map(_norm_ticker)
    sector_map = master.set_index("ticker")["sector"].to_dict()
    tickers = master["ticker"].tolist()
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
    month = int(target_month[5:7])
    # 대상월 기준 직전 확정 사업연도 (3월 이전은 Y-2가 더 안정적인 경우 있음)
    fin_year = year - 2 if month <= 3 else year - 1

    ensure_factor_columns(conn)

    rows = []
    ok_fund = 0
    ok_cf = 0
    for i, ticker in enumerate(tickers, 1):
        mom = mom_map.get(ticker, {})
        fund: Dict[str, Optional[float]] = {k: None for k in ACCOUNT_ALIASES}
        prev_fund: Optional[Dict[str, Optional[float]]] = None
        if dart is not None:
            df_fin = fetch_finstate_cached(dart, ticker, fin_year, sleep_sec=sleep_sec)
            if not df_fin.empty:
                fund = extract_fundamentals(df_fin)
                if any(v is not None for v in fund.values()):
                    ok_fund += 1
            # Phase A3–A4: CFO/CapEx 는 전체재무제표 API
            df_all = fetch_finstate_all_cached(dart, ticker, fin_year, sleep_sec=sleep_sec)
            if not df_all.empty:
                fund = merge_fundamentals(fund, extract_fundamentals(df_all))
                if fund.get("cfo") is not None:
                    ok_cf += 1
            # F-Score YoY용 전년 (캐시 hit면 sleep 거의 없음)
            df_prev = fetch_finstate_cached(dart, ticker, fin_year - 1, sleep_sec=0.05)
            if not df_prev.empty:
                prev_fund = extract_fundamentals(df_prev)
            df_prev_all = fetch_finstate_all_cached(dart, ticker, fin_year - 1, sleep_sec=0.05)
            if not df_prev_all.empty and prev_fund is not None:
                prev_fund = merge_fundamentals(prev_fund, extract_fundamentals(df_prev_all))
            elif not df_prev_all.empty:
                prev_fund = extract_fundamentals(df_prev_all)

        marcap = marcap_map.get(ticker)
        # 시총 없으면 종가×상장주식수 근사
        if marcap is None and not listing.empty and mom.get("close"):
            hit = listing[listing["ticker"] == ticker]
            if not hit.empty and "stocks" in hit.columns:
                stocks = _to_float(hit.iloc[0].get("stocks"))
                if stocks:
                    marcap = float(mom["close"]) * stocks

        rows.append(
            build_row(
                ticker,
                target_month,
                mom,
                fund,
                marcap,
                prev_fund,
                sector=sector_map.get(ticker),
            )
        )
        if i % 50 == 0 or i == len(tickers):
            print(f"  [{i}/{len(tickers)}] 진행 | DART재무 {ok_fund} | CFO {ok_cf}")

    conn.close()
    out = pd.DataFrame(rows)
    upsert_factors(rows)
    print(f"📊 DART 재무 매핑 성공: {ok_fund}/{len(tickers)}")
    print(f"📊 CFO 확보: {ok_cf}/{len(tickers)}")
    print(f"📊 accrual 비결측: {out['accrual'].notna().sum()}")
    print(f"📊 fcf_yield 비결측: {out['fcf_yield'].notna().sum()}")
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
