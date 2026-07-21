# -*- coding: utf-8 -*-
"""
제품 #4 MVP: 로컬 SQLite 회원(가입/로그인)
- 비밀번호: PBKDF2-SHA256 (표준 라이브러리)
- DB: data_cache/users.db
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from datetime import datetime
from typing import Any, Optional

USERS_DB = os.path.abspath("./data_cache/users.db")
_PBKDF2_ITER = 200_000


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(USERS_DB), exist_ok=True)
    conn = sqlite3.connect(USERS_DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_users_table() -> None:
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'free',
            created_at TEXT NOT NULL,
            last_login_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def _hash_password(password: str, salt_hex: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        _PBKDF2_ITER,
    )
    return dk.hex()


def register_user(
    email: str,
    password: str,
    display_name: str,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    """가입. 성공 시 (True, msg, user_dict)."""
    ensure_users_table()
    email_n = _normalize_email(email)
    name = (display_name or "").strip() or email_n.split("@")[0]
    if not _valid_email(email_n):
        return False, "이메일 형식이 올바르지 않습니다.", None
    if len(password) < 8:
        return False, "비밀번호는 8자 이상이어야 합니다.", None
    if len(name) > 40:
        return False, "닉네임은 40자 이내로 입력하세요.", None

    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO users (email, display_name, password_hash, salt, tier, created_at)
            VALUES (?, ?, ?, ?, 'free', ?)
            """,
            (email_n, name, pw_hash, salt, now),
        )
        conn.commit()
        uid = cur.lastrowid
        return True, "가입이 완료되었습니다.", {
            "id": uid,
            "email": email_n,
            "display_name": name,
            "tier": "free",
        }
    except sqlite3.IntegrityError:
        return False, "이미 등록된 이메일입니다.", None
    except Exception as e:
        return False, f"가입 실패: {e}", None
    finally:
        conn.close()


def authenticate(
    email: str,
    password: str,
) -> tuple[bool, str, Optional[dict[str, Any]]]:
    ensure_users_table()
    email_n = _normalize_email(email)
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT id, email, display_name, password_hash, salt, tier
            FROM users WHERE email = ?
            """,
            (email_n,),
        ).fetchone()
        if not row:
            return False, "이메일 또는 비밀번호가 올바르지 않습니다.", None
        uid, em, name, pw_hash, salt, tier = row
        if _hash_password(password, salt) != pw_hash:
            return False, "이메일 또는 비밀번호가 올바르지 않습니다.", None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (now, uid),
        )
        conn.commit()
        return True, "로그인되었습니다.", {
            "id": uid,
            "email": em,
            "display_name": name,
            "tier": tier or "free",
        }
    finally:
        conn.close()


def user_from_session(session_user: Any) -> Optional[dict[str, Any]]:
    if not isinstance(session_user, dict):
        return None
    if not session_user.get("id") or not session_user.get("email"):
        return None
    return session_user
