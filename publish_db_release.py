"""
로컬 quant_history.db 를 GitHub Release(quant-db-latest)에 업로드.
사전: gh auth login && pip install zstandard
사용: python publish_db_release.py
"""
from __future__ import annotations

import os
import subprocess
import sys

ZST_PATH = os.path.abspath("./data_cache/quant_history.db.zst")
DB_PATH = os.path.abspath("./data_cache/quant_history.db")
TAG = "quant-db-latest"


def main():
    if not os.path.exists(DB_PATH):
        print("DB 없음:", DB_PATH)
        sys.exit(1)

    from db_snapshot import compress
    compress()

    check = subprocess.run(["gh", "release", "view", TAG], capture_output=True, text=True)
    if check.returncode != 0:
        print(f"Release '{TAG}' 생성...")
        subprocess.check_call([
            "gh", "release", "create", TAG, ZST_PATH,
            "--title", "Quant History DB (latest)",
            "--notes", "GitHub Actions 일일 업데이트용 SQLite 스냅샷 (zstd)",
        ])
    else:
        print(f"Release '{TAG}' 업로드(덮어쓰기)...")
        subprocess.check_call(["gh", "release", "upload", TAG, ZST_PATH, "--clobber"])
    print("완료. GitHub Secrets에 QUANTKING_EMAIL/PASSWORD 또는 TOKEN을 넣고 Actions를 켜세요.")


if __name__ == "__main__":
    main()
