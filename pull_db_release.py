"""
GitHub Release(quant-db-latest)에서 최신 DB를 받아 로컬 data_cache 에 복원.
대시보드 실행 전: python pull_db_release.py
"""
from __future__ import annotations

import os
import subprocess
import sys

TAG = "quant-db-latest"
ZST = os.path.abspath("./data_cache/quant_history.db.zst")


def main():
    os.makedirs("data_cache", exist_ok=True)
    subprocess.check_call(
        ["gh", "release", "download", TAG, "-p", "quant_history.db.zst", "-D", "data_cache", "--clobber"]
    )
    from db_snapshot import decompress
    decompress()
    print("✅ 로컬 DB 동기화 완료. streamlit run dashboard_v2.py")


if __name__ == "__main__":
    main()
