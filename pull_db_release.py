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
    # Streamlit 등이 DB를 연 상태면 WAL 삭제가 실패 → 복원 후 malformed
    db = os.path.abspath("./data_cache/quant_history.db")
    for side in (db, db + "-wal", db + "-shm"):
        try:
            if os.path.exists(side) and side != db:
                os.remove(side)
        except OSError as e:
            print(f"[warn] {os.path.basename(side)} 삭제 실패 (대시보드를 먼저 종료하세요): {e}")
    subprocess.check_call(
        ["gh", "release", "download", TAG, "-p", "quant_history.db.zst", "-D", "data_cache", "--clobber"]
    )
    from db_snapshot import decompress
    decompress()
    print("✅ 로컬 DB 동기화 완료. streamlit run dashboard_v2.py")


if __name__ == "__main__":
    main()
