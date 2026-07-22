# -*- coding: utf-8 -*-
"""
일일 Actions / 로컬 ETL 요약 메일.

GitHub Secrets (권장):
  SMTP_USER       — Gmail 주소 (발신)
  SMTP_PASSWORD   — Gmail 앱 비밀번호 (일반 비밀번호 아님)
  NOTIFY_TO       — 수신 주소 (여러 개면 쉼표 구분)

환경변수 (Actions가 주입):
  JOB_STATUS, GITHUB_RUN_URL, GATE_RESULT(선택)

시크릿이 없으면 메일 없이 요약을 stdout만 출력하고 exit 0.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import List, Optional


def _db_summary(db_path: str) -> str:
    if not os.path.exists(db_path):
        return "(DB 파일 없음 — 파이프라인 초반 실패 가능)"
    try:
        from db_quality_gate import evaluate_gate, latest_factor_coverage

        ok, msg, _ = evaluate_gate(db_path)
        info = latest_factor_coverage(db_path)
        lines = [f"게이트: {'PASS' if ok else 'FAIL'} — {msg}"]
        latest = (info or {}).get("latest") or {}
        if latest:
            lines.append(
                f"최신월 {latest.get('date')}: n={latest.get('n')} "
                f"per={latest.get('per_cov', 0):.1%} "
                f"pbr={latest.get('pbr_cov', 0):.1%} "
                f"roe={latest.get('roe_cov', 0):.1%}"
            )
        prev = (info or {}).get("prev")
        if prev:
            lines.append(
                f"직전월 {prev.get('date')}: n={prev.get('n')} "
                f"per={prev.get('per_cov', 0):.1%}"
            )
        return "\n".join(lines)
    except SystemExit:
        raise
    except Exception as e:
        return f"(DB 요약 실패: {e})"


def _recipients(raw: str) -> List[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def build_body() -> tuple[str, str]:
    status = (os.getenv("JOB_STATUS") or "unknown").lower()
    run_url = os.getenv("GITHUB_RUN_URL") or ""
    repo = os.getenv("GITHUB_REPOSITORY") or ""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    db = os.path.abspath("./data_cache/quant_history.db")

    flag = "OK" if status == "success" else status.upper()
    subject = f"[Quant Lab] 일일 적재 {flag} · {now[:10]}"

    parts = [
        f"상태: {status}",
        f"시각: {now}",
        f"리포: {repo or '(local)'}",
    ]
    if run_url:
        parts.append(f"Actions: {run_url}")
    parts.append("")
    parts.append("--- DB / 게이트 ---")
    parts.append(_db_summary(db))
    parts.append("")
    parts.append(
        "※ DB 파일 자체는 메일로 보내지 않습니다. "
        "Release quant-db-latest 또는 날짜 태그를 확인하세요."
    )
    return subject, "\n".join(parts)


def send_mail(subject: str, body: str) -> bool:
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    to_raw = (os.getenv("NOTIFY_TO") or os.getenv("SMTP_TO") or "").strip()
    host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT") or "587")
    tos = _recipients(to_raw)

    if not user or not password or not tos:
        print(
            "[notify] SMTP_USER / SMTP_PASSWORD / NOTIFY_TO 미설정 — 메일 생략",
            flush=True,
        )
        print(body, flush=True)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(tos)
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=60) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(user, password)
        server.send_message(msg)
    print(f"[notify] 메일 발송 완료 → {', '.join(tos)}", flush=True)
    return True


def main(argv: Optional[list[str]] = None) -> None:
    subject, body = build_body()
    try:
        send_mail(subject, body)
    except Exception as e:
        # 메일 실패로 전체 Actions를 빨갛게 만들지 않음
        print(f"[notify] 발송 실패(무시): {e}", flush=True)
        print(body, flush=True)
        raise SystemExit(0)


if __name__ == "__main__":
    main()
