# -*- coding: utf-8 -*-
"""
Phase A3–A4 백필: DART 전체재무제표(finstate_all)로 accrual / fcf_yield 만 UPDATE.
기존 PER/모멘텀 등 다른 컬럼은 건드리지 않음.

예:
  python backfill_accrual_fcf.py --month 2026-07 --limit 40
  python backfill_accrual_fcf.py --all-months --from-month 2020-04 --sleep 0.5
  python backfill_accrual_fcf.py --all-months --resume --sleep 0.5
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import time
import traceback
from typing import Dict, List, Optional, Tuple

import pandas as pd

from factor_builder import (
    DartQuotaExceeded,
    _connect,
    _dart_api_keys,
    _init_dart,
    _norm_ticker,
    compute_accrual,
    compute_fcf_yield,
    ensure_factor_columns,
    extract_fundamentals,
    fetch_finstate_all_cached,
    fetch_finstate_cached,
    is_financial_sector,
    load_listings_marcap,
    merge_fundamentals,
)

PROGRESS_PATH = os.path.abspath("./data_cache/accrual_fcf_progress.txt")
LIVE_LOG = os.path.abspath("./data_cache/accrual_fcf_live.log")


def _fin_year(ym: str, override: Optional[int] = None) -> int:
    if override is not None:
        return override
    y = int(ym[:4])
    m = int(ym[5:7])
    return y - 2 if m <= 3 else y - 1


def _read_progress() -> Dict[str, str]:
    if not os.path.exists(PROGRESS_PATH):
        return {}
    out: Dict[str, str] = {}
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except Exception:
        return {}
    return out


def _parse_resume_month(prog: Dict[str, str]) -> Optional[str]:
    """progress.txt 에서 재개 시작월(YYYY-MM) 추출."""
    for key in ("resume_month", "month"):
        v = prog.get(key, "")
        if len(v) >= 7 and v[4] == "-":
            return v[:7]
    cur = prog.get("current", "")
    for prefix in ("QUOTA_HALT@", "ERROR_HALT@", "CRASH@"):
        if cur.startswith(prefix):
            ym = cur[len(prefix) : len(prefix) + 7]
            if len(ym) == 7 and ym[4] == "-":
                return ym
    if len(cur) >= 7 and cur[4] == "-" and cur[:4].isdigit():
        return cur[:7]
    return None


def _first_incomplete_month(
    conn,
    months: List[str],
    *,
    min_both_pct: float = 0.35,
) -> Optional[str]:
    """DB 기준으로 accrual+fcf 둘 다 있는 비율이 낮은 첫 월."""
    cur = conn.cursor()
    for ym in months:
        n = cur.execute(
            "SELECT count(*) FROM monthly_factor WHERE date=?", (ym,)
        ).fetchone()[0]
        if n <= 0:
            return ym
        both = cur.execute(
            """
            SELECT count(*) FROM monthly_factor
            WHERE date=? AND accrual IS NOT NULL AND fcf_yield IS NOT NULL
            """,
            (ym,),
        ).fetchone()[0]
        if (both / n) < min_both_pct:
            return ym
    return None


def _write_progress(
    *,
    done: int,
    total: int,
    ok_acc: int,
    ok_fcf: int,
    current: str,
    t0: float,
    phase: str = "accrual_fcf",
    resume_month: Optional[str] = None,
    status: str = "running",
    last_error: str = "",
) -> None:
    elapsed = time.time() - t0
    rate = done / elapsed if elapsed > 0 and done else 0
    eta = (total - done) / rate if rate > 0 else 0
    pct = 100.0 * done / total if total else 0
    rm = resume_month or ""
    if not rm:
        rm = _parse_resume_month({"current": current}) or ""
    body = (
        f"phase={phase}\n"
        f"status={status}\n"
        f"progress={done}/{total}\n"
        f"percent={pct:.2f}\n"
        f"ok_accrual={ok_acc}\n"
        f"ok_fcf={ok_fcf}\n"
        f"elapsed_sec={elapsed:.0f}\n"
        f"eta_sec={eta:.0f}\n"
        f"current={current}\n"
        f"resume_month={rm}\n"
        f"last_error={last_error[:200]}\n"
        f"updated={time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        f.write(body)
    line = (
        f"A3 [{done}/{total} {pct:.1f}%] acc={ok_acc} fcf={ok_fcf} "
        f"elapsed={elapsed/60:.0f}m ETA={eta/60:.0f}m now={current}  "
        f"{time.strftime('%H:%M:%S')}\n"
    )
    with open(LIVE_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    print(line.rstrip(), flush=True)


def _quiet_fetch(fn, *args, **kwargs):
    """OpenDartReader의 status 013 print 스팸을 숨김."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return fn(*args, **kwargs)


def _log_line(msg: str) -> None:
    print(msg, flush=True)
    os.makedirs(os.path.dirname(LIVE_LOG), exist_ok=True)
    with open(LIVE_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def _backfill_month(
    conn,
    dart,
    month: str,
    fin_year: int,
    master: pd.DataFrame,
    marcap_map: Dict[str, float],
    sleep_sec: float,
    skip_filled: bool,
    *,
    month_i: int = 1,
    month_n: int = 1,
    t0: Optional[float] = None,
    sum_acc: int = 0,
    sum_fcf: int = 0,
) -> Tuple[int, int, int]:
    """한 달 백필. 반환: (처리시도, ok_acc, ok_fcf)"""
    cur = conn.cursor()
    ok_acc = ok_fcf = tried = empty = 0
    t_month = time.time()
    n_master = len(master)

    if skip_filled:
        filled = {
            r[0]
            for r in cur.execute(
                """
                SELECT ticker FROM monthly_factor
                WHERE date=? AND accrual IS NOT NULL AND fcf_yield IS NOT NULL
                """,
                (month,),
            )
        }
    else:
        filled = set()

    skipped = len(filled)
    if skipped:
        _log_line(
            f"A3 [{month_i}/{month_n}] {month} skip_filled={skipped}/{n_master} "
            f"(이어서 미완료 종목만)"
        )

    for row in master.itertuples(index=False):
        ticker, sector = row.ticker, row.sector
        if ticker in filled:
            continue
        tried += 1
        try:
            df_all = _quiet_fetch(
                fetch_finstate_all_cached, dart, ticker, fin_year, sleep_sec=sleep_sec
            )
        except DartQuotaExceeded:
            conn.commit()
            raise
        if df_all.empty:
            empty += 1
            if tried % 25 == 0 or tried == 1:
                elapsed = time.time() - (t0 or t_month)
                _log_line(
                    f"A3 [{month_i}/{month_n}] {month} ticker={tried}/{n_master} "
                    f"{ticker} | acc={ok_acc} fcf={ok_fcf} empty={empty} "
                    f"elapsed={elapsed/60:.1f}m"
                )
            continue
        fund = extract_fundamentals(df_all)
        try:
            df_bs = _quiet_fetch(
                fetch_finstate_cached, dart, ticker, fin_year, sleep_sec=0.05
            )
        except DartQuotaExceeded:
            conn.commit()
            raise
        if not df_bs.empty:
            fund = merge_fundamentals(extract_fundamentals(df_bs), fund)

        accrual = compute_accrual(fund)
        fcf = compute_fcf_yield(
            fund, marcap_map.get(ticker), financial=is_financial_sector(sector)
        )
        cur.execute(
            """
            UPDATE monthly_factor
            SET accrual = ?, fcf_yield = ?
            WHERE date = ? AND ticker = ?
            """,
            (accrual, fcf, month, ticker),
        )
        if accrual is not None:
            ok_acc += 1
        if fcf is not None:
            ok_fcf += 1

        if tried % 25 == 0 or tried == 1 or tried == n_master:
            elapsed = time.time() - (t0 or t_month)
            _log_line(
                f"A3 [{month_i}/{month_n}] {month} ticker={tried}/{n_master} "
                f"{ticker} | acc={ok_acc} fcf={ok_fcf} empty={empty} "
                f"elapsed={elapsed/60:.1f}m"
            )
            conn.commit()
            _write_progress(
                done=max(0, month_i - 1),
                total=month_n,
                ok_acc=sum_acc + ok_acc,
                ok_fcf=sum_fcf + ok_fcf,
                current=f"{month}#{ticker}",
                t0=t0 or t_month,
                resume_month=month,
                status="running",
            )

    conn.commit()
    return tried, ok_acc, ok_fcf


def _load_month_master(conn, month: str, limit: Optional[int]) -> pd.DataFrame:
    master = pd.read_sql(
        """
        SELECT f.ticker, m.sector
        FROM monthly_factor f
        JOIN stock_master m ON f.ticker = m.ticker
        WHERE f.date = ? AND m.is_active = 1
        """,
        conn,
        params=(month,),
    )
    master["ticker"] = master["ticker"].map(_norm_ticker)
    if limit:
        master = master.head(limit)
    return master


def main():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--month", type=str, default=None, help="YYYY-MM (기본: DB 최신월)")
    p.add_argument("--all-months", action="store_true", help="monthly_factor 전 월 백필")
    p.add_argument(
        "--from-month",
        type=str,
        default=None,
        help="YYYY-MM 이상만 (예: 2020-04부터)",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="progress.txt/DB 기준으로 중단 지점부터 재개 (한도·일반오류 공통)",
    )
    p.add_argument("--limit", type=int, default=None, help="월별 종목 수 제한(테스트)")
    p.add_argument("--sleep", type=float, default=0.5)
    p.add_argument("--year", type=int, default=None, help="재무연도 고정(단일 월용)")
    p.add_argument(
        "--force",
        action="store_true",
        help="이미 accrual+fcf 있는 종목도 다시 계산",
    )
    args = p.parse_args()

    conn = _connect()
    ensure_factor_columns(conn)

    if args.all_months:
        months: List[str] = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM monthly_factor ORDER BY date"
            ).fetchall()
        ]
    else:
        month = args.month or conn.execute(
            "SELECT max(date) FROM monthly_factor"
        ).fetchone()[0]
        if not month:
            print("❌ monthly_factor 비어 있음")
            return
        months = [month]

    from_month = args.from_month.strip() if args.from_month else None

    if args.resume and not from_month:
        prog = _read_progress()
        from_month = _parse_resume_month(prog)
        if from_month:
            print(
                f"⏯ resume progress → {from_month} "
                f"(status={prog.get('status', '?')} current={prog.get('current', '')})",
                flush=True,
            )
        else:
            from_month = _first_incomplete_month(conn, months)
            if from_month:
                print(f"⏯ resume DB 미완료 첫 월 → {from_month}", flush=True)

    if from_month:
        months = [m for m in months if m >= from_month]
        print(f"⏩ from-month={from_month} → {len(months)}개월", flush=True)

    if not months:
        print("❌ 대상 월 없음")
        return

    listing = load_listings_marcap()
    marcap_map: Dict[str, float] = {}
    if not listing.empty and "marcap" in listing.columns:
        marcap_map = listing.set_index("ticker")["marcap"].to_dict()

    dart_keys = _dart_api_keys()
    if not dart_keys:
        print("❌ DART_API_KEY 없음 — .env에 주 키(및 선택) DART_API_KEY_BACKUP 설정")
        return
    key_i = 0
    dart = _init_dart(dart_keys[key_i])
    if dart is None:
        print("❌ DART 초기화 실패 — API 키/패키지 확인")
        return
    if len(dart_keys) > 1:
        print(
            f"🔑 DART 키 {len(dart_keys)}개 (주+예비). 020 시 자동 전환합니다.",
            flush=True,
        )

    skip_filled = not args.force
    total = len(months)
    print(
        f"🚀 accrual/fcf 백필 | months={total} | sleep={args.sleep} | "
        f"skip_filled={skip_filled} | resume={bool(args.resume)}",
        flush=True,
    )
    if (not args.resume) and os.path.exists(LIVE_LOG):
        os.remove(LIVE_LOG)

    t0 = time.time()
    sum_acc = sum_fcf = 0
    i = 0
    while i < total:
        ym = months[i]
        month_i = i + 1
        fy = _fin_year(ym, args.year if not args.all_months else None)
        master = _load_month_master(conn, ym, args.limit)
        if args.limit and month_i == 1:
            print(f"🔬 limit={args.limit}", flush=True)
        _log_line(f"—— [{month_i}/{total}] {ym} fin_year={fy} tickers={len(master)} ——")
        _write_progress(
            done=max(0, month_i - 1),
            total=total,
            ok_acc=sum_acc,
            ok_fcf=sum_fcf,
            current=ym,
            t0=t0,
            resume_month=ym,
            status="running",
        )
        try:
            tried, ok_acc, ok_fcf = _backfill_month(
                conn,
                dart,
                ym,
                fy,
                master,
                marcap_map,
                args.sleep,
                skip_filled,
                month_i=month_i,
                month_n=total,
                t0=t0,
                sum_acc=sum_acc,
                sum_fcf=sum_fcf,
            )
        except DartQuotaExceeded as e:
            if key_i + 1 < len(dart_keys):
                key_i += 1
                dart = _init_dart(dart_keys[key_i])
                if dart is not None:
                    _log_line(
                        f"🔄 DART 일일 한도(020) → 예비 키 #{key_i + 1}로 전환, "
                        f"{ym}부터 이어서 재시도. ({e})"
                    )
                    try:
                        conn.commit()
                    except Exception:
                        pass
                    continue
                _log_line("❌ 백업 DART 키 초기화 실패 — 중단")
            msg = (
                f"⛔ DART 일일 한도 초과(020) — 사용 가능 키 소진 at {ym} fin_year={fy}. "
                f"{e} | 재개: python backfill_accrual_fcf.py --all-months --resume --sleep 0.5"
            )
            _log_line(msg)
            try:
                conn.commit()
            except Exception:
                pass
            _write_progress(
                done=max(0, month_i - 1),
                total=total,
                ok_acc=sum_acc,
                ok_fcf=sum_fcf,
                current=f"QUOTA_HALT@{ym}",
                t0=t0,
                resume_month=ym,
                status="quota_halt",
                last_error=str(e),
            )
            conn.close()
            raise SystemExit(2) from e
        except KeyboardInterrupt as e:
            _log_line(f"⛔ 사용자 중단 at {ym} — --resume 로 이어서 가능")
            try:
                conn.commit()
            except Exception:
                pass
            _write_progress(
                done=max(0, month_i - 1),
                total=total,
                ok_acc=sum_acc,
                ok_fcf=sum_fcf,
                current=f"ERROR_HALT@{ym}",
                t0=t0,
                resume_month=ym,
                status="error_halt",
                last_error="KeyboardInterrupt",
            )
            conn.close()
            raise SystemExit(130) from e
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            _log_line(f"⛔ 오류 중단 at {ym}: {err}")
            _log_line(traceback.format_exc()[-800:])
            try:
                conn.commit()
            except Exception:
                pass
            _write_progress(
                done=max(0, month_i - 1),
                total=total,
                ok_acc=sum_acc,
                ok_fcf=sum_fcf,
                current=f"ERROR_HALT@{ym}",
                t0=t0,
                resume_month=ym,
                status="error_halt",
                last_error=err,
            )
            conn.close()
            raise SystemExit(1) from e

        sum_acc += ok_acc
        sum_fcf += ok_fcf
        next_m = months[i + 1] if (i + 1) < total else "DONE"
        _write_progress(
            done=month_i,
            total=total,
            ok_acc=sum_acc,
            ok_fcf=sum_fcf,
            current=f"{ym}(+{ok_acc}/{ok_fcf},tried={tried})",
            t0=t0,
            resume_month=next_m if next_m != "DONE" else ym,
            status="running" if next_m != "DONE" else "done",
        )
        i += 1

    conn.close()
    print(
        f"✅ 전체 완료 {time.time()-t0:.1f}s | months={total} | "
        f"accrual_updates≈{sum_acc} | fcf_updates≈{sum_fcf}",
        flush=True,
    )
    _write_progress(
        done=total,
        total=total,
        ok_acc=sum_acc,
        ok_fcf=sum_fcf,
        current="DONE",
        t0=t0,
        resume_month="",
        status="done",
    )


if __name__ == "__main__":
    main()
