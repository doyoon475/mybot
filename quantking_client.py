"""
퀀트킹 멤버십 게시판 API 클라이언트 (Selenium 없이 일일 수집용).

인증 우선순위:
1) QUANTKING_TOKEN  (브라우저 localStorage 'token' 값)
2) QUANTKING_EMAIL + QUANTKING_PASSWORD  (또는 QUANTKING_ID + PASSWORD)
"""
from __future__ import annotations

import os
import re
import time
import random
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://api.quantking.net/api/v1/user/"
LOGIN_URL = API_BASE + "member/login"
MEMBERSHIP_LIST = API_BASE + "board/membership"
MEMBERSHIP_DETAIL = API_BASE + "board/membership/{no}"


def _blob_get(url: str, timeout: int = 120) -> requests.Response:
    """Azure Blob에는 Authorization을 붙이지 않는다."""
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quantking.net/",
        "Accept": "*/*",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp


def _safe_filename(name: str) -> str:
    name = (name or "").strip().replace("\n", " ")
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name[:180] if name else f"quant_{int(time.time())}.xlsx"


class QuantKingClient:
    def __init__(self, token: Optional[str] = None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json",
            "Origin": "https://quantking.net",
            "Referer": "https://quantking.net/",
        })
        self.token = token or os.getenv("QUANTKING_TOKEN", "").strip()
        if self.token:
            self._set_token(self.token)

    def _set_token(self, token: str):
        self.token = token
        if token.lower().startswith("bearer "):
            self.session.headers["Authorization"] = token
        else:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def login(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> str:
        if self.token:
            return self.token

        email = (email or os.getenv("QUANTKING_EMAIL") or os.getenv("QUANTKING_ID") or "").strip()
        password = (password or os.getenv("QUANTKING_PASSWORD") or "").strip()
        if not email or not password:
            raise RuntimeError(
                "QUANTKING_TOKEN 또는 QUANTKING_EMAIL/PASSWORD 환경변수가 필요합니다."
            )

        payloads = [
            {"email": email, "password": password},
            {"id": email, "password": password},
            {"userId": email, "password": password},
            {"loginId": email, "password": password},
        ]
        last_err = None
        for body in payloads:
            try:
                resp = self.session.put(LOGIN_URL, json=body, timeout=30)
                if resp.status_code >= 400:
                    last_err = f"{resp.status_code} {resp.text[:200]}"
                    continue
                data = resp.json()
                token = (
                    data.get("token")
                    or data.get("accessToken")
                    or (data.get("data") or {}).get("token")
                    or (data.get("data") or {}).get("accessToken")
                )
                if not token and isinstance(data.get("data"), str):
                    token = data["data"]
                if not token:
                    last_err = f"토큰 필드 없음: {str(data)[:200]}"
                    continue
                self._set_token(token)
                print("✅ 퀀트킹 API 로그인 성공")
                return token
            except Exception as e:
                last_err = str(e)
                continue
        raise RuntimeError(f"퀀트킹 로그인 실패: {last_err}")

    def _get_json(self, url: str, params: Optional[dict] = None) -> Any:
        resp = self.session.get(url, params=params, timeout=60)
        if resp.status_code == 401 and "Bearer " in self.session.headers.get("Authorization", ""):
            raw = self.session.headers["Authorization"].replace("Bearer ", "", 1)
            self.session.headers["Authorization"] = raw
            resp = self.session.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "data" in data and len(data) <= 4:
            return data["data"]
        return data

    def list_membership(self, page: int = 1, limit: int = 10) -> List[dict]:
        data = self._get_json(MEMBERSHIP_LIST, {"page": page, "limit": limit})
        if isinstance(data, dict):
            return data.get("items") or data.get("list") or []
        if isinstance(data, list):
            return data
        return []

    def get_membership_detail(self, no: Any) -> dict:
        data = self._get_json(MEMBERSHIP_DETAIL.format(no=no))
        return data if isinstance(data, dict) else {}

    def download_file(self, url: str, dest_dir: str, title_hint: str = "") -> Tuple[str, bool]:
        os.makedirs(dest_dir, exist_ok=True)
        resp = _blob_get(url)
        # ETL이 파일명에서 YYYY.MM.DD 를 뽑으므로 제목 날짜를 파일명에 우선 반영
        date_m = re.search(r"20\d{2}\.\d{2}\.\d{2}", title_hint or "")
        if date_m:
            fname = _safe_filename(f"퀀트데이터{date_m.group(0)}.xlsx")
        else:
            fname = url.split("?")[0].rstrip("/").split("/")[-1]
            if not fname or "." not in fname:
                fname = _safe_filename(re.sub(r"\s+", "", title_hint)[:40] + ".xlsx")
            else:
                fname = _safe_filename(fname)
        path = os.path.join(dest_dir, fname)
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return fname, True
        with open(path, "wb") as f:
            f.write(resp.content)
        if os.path.getsize(path) < 500:
            os.remove(path)
            raise RuntimeError(f"파일 너무 작음: {fname}")
        return fname, False


def fetch_latest_quant_files(
    dest_dir: str = "./quant_raw_data",
    pages: int = 2,
    title_keyword: str = "퀀트데이터",
) -> Dict[str, int]:
    """
    최신 멤버십 게시물(기본 1~2페이지)에서 퀀트데이터 첨부만 받아 저장.
    반환: {ok, skip, fail}
    """
    client = QuantKingClient()
    client.login()

    stats = {"ok": 0, "skip": 0, "fail": 0}
    os.makedirs(dest_dir, exist_ok=True)

    for page in range(1, pages + 1):
        print(f"📥 [퀀트킹] 멤버십 목록 page={page}")
        try:
            items = client.list_membership(page=page, limit=10)
        except Exception as e:
            print(f"  ❌ 목록 실패: {e}")
            stats["fail"] += 1
            continue

        if not items:
            print("  게시물 없음")
            continue

        for item in items:
            title = str(item.get("title") or "")
            compact = re.sub(r"\s+", "", title)
            if title_keyword not in compact and title_keyword not in title:
                continue
            post_no = item.get("no") or item.get("id")
            try:
                detail = client.get_membership_detail(post_no)
                files = detail.get("fileList") or []
                if not files:
                    print(f"  ⚠️ fileList 없음: {title[:40]}")
                    stats["fail"] += 1
                    continue
                for furl in files:
                    if not isinstance(furl, str) or not furl.startswith("http"):
                        continue
                    fname, already = client.download_file(furl, dest_dir, title)
                    if already:
                        print(f"  [스킵] {fname[:50]}")
                        stats["skip"] += 1
                    else:
                        print(f"  [저장] {fname[:50]}")
                        stats["ok"] += 1
                    time.sleep(random.uniform(0.4, 0.9))
            except Exception as e:
                print(f"  ❌ [{post_no}] {title[:30]}: {e}")
                stats["fail"] += 1
                time.sleep(1.0)

        time.sleep(random.uniform(0.8, 1.5))

    print(
        f"✅ 퀀트킹 수집 완료 | 신규 {stats['ok']} / 스킵 {stats['skip']} / 실패 {stats['fail']}"
    )
    return stats


if __name__ == "__main__":
    fetch_latest_quant_files(pages=2)
