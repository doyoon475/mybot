# -*- coding: utf-8 -*-
"""
C9 백필 워치독: progress 파일이 N분 이상 갱신되지 않으면 프로세스 재시작.
이미 적재분은 skip_existing 으로 이어감.

  python -u scripts/c9_watchdog.py
  python -u scripts/c9_watchdog.py --stall-min 10 --sleep 0.5
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROGRESS = os.path.join(ROOT, "data_cache", "c9_progress.txt")
LIVE = os.path.join(ROOT, "data_cache", "c9_live.log")
WATCHDOG_LOG = os.path.join(ROOT, "data_cache", "c9_watchdog.log")


def _log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(WATCHDOG_LOG), exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _parse_progress(path: str) -> dict:
    out: dict = {}
    if not os.path.exists(path):
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _updated_age_sec(info: dict) -> Optional[float]:
    raw = info.get("updated")
    if not raw:
        # fallback: file mtime
        try:
            return time.time() - os.path.getmtime(PROGRESS)
        except OSError:
            return None
    try:
        ts = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return time.time() - ts.timestamp()
    except ValueError:
        try:
            return time.time() - os.path.getmtime(PROGRESS)
        except OSError:
            return None


def _find_c9_pids() -> List[int]:
    """Windows: wmic/cim 없이 tasklist + cmdline 근사. PowerShell 사용."""
    try:
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*quarterly_panel*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
        )
        pids = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    except Exception as e:
        _log(f"[warn] pid 조회 실패: {e}")
        return []


def _kill_pids(pids: List[int]) -> None:
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            _log(f"killed pid={pid}")
        except Exception as e:
            _log(f"[warn] kill {pid}: {e}")


def _start_c9(sleep_sec: float, min_year: int) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    args = [
        sys.executable,
        "-u",
        os.path.join(ROOT, "quarterly_panel.py"),
        "--fetch",
        "--min-year",
        str(min_year),
        "--sleep",
        str(sleep_sec),
        "--apply",
    ]
    # DETACHED on Windows so watchdog exit doesn't kill child
    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creationflags |= subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
    subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    _log(f"started C9: {' '.join(args[2:])}")


def main() -> None:
    p = argparse.ArgumentParser(description="C9 stall watchdog")
    p.add_argument("--stall-min", type=float, default=10.0, help="재시작까지 무갱신 분")
    p.add_argument("--check-sec", type=float, default=60.0, help="점검 주기(초)")
    p.add_argument("--sleep", type=float, default=0.5, help="C9 --sleep")
    p.add_argument("--min-year", type=int, default=2018)
    args = p.parse_args()

    stall_sec = max(60.0, args.stall_min * 60.0)
    _log(
        f"watchdog start stall={args.stall_min}min check={args.check_sec}s "
        f"min_year={args.min_year} sleep={args.sleep}"
    )

    while True:
        info = _parse_progress(PROGRESS)
        ticker = info.get("current_ticker", "")
        pids = _find_c9_pids()
        age = _updated_age_sec(info)

        if ticker == "DONE":
            if not pids:
                _log("C9 DONE — watchdog exit")
                return
            _log("fetch DONE, apply/프로세스 종료 대기…")
            time.sleep(args.check_sec)
            continue

        if not pids:
            _log("C9 process 없음 → 재시작")
            _start_c9(args.sleep, args.min_year)
            time.sleep(args.check_sec)
            continue

        if age is None:
            _log("progress 없음/파싱 실패 — 대기")
            time.sleep(args.check_sec)
            continue

        if age >= stall_sec:
            _log(
                f"STALL {age/60:.1f}min (>{args.stall_min}min) "
                f"at {info.get('progress')} now={info.get('current_ticker')} → restart"
            )
            _kill_pids(pids)
            time.sleep(3)
            _start_c9(args.sleep, args.min_year)
        else:
            _log(
                f"ok age={age/60:.1f}min progress={info.get('progress')} "
                f"pids={pids}"
            )

        time.sleep(args.check_sec)


if __name__ == "__main__":
    main()
