"""CI/로컬 공용: quant_history.db <-> quant_history.db.zst"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

try:
    import zstandard as zstd
except ImportError:
    print("pip install zstandard 필요")
    sys.exit(1)

DB = os.path.abspath("./data_cache/quant_history.db")
ZST = os.path.abspath("./data_cache/quant_history.db.zst")


def decompress():
    if not os.path.exists(ZST):
        print("없음:", ZST)
        sys.exit(1)
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    dctx = zstd.ZstdDecompressor()
    with open(ZST, "rb") as src, open(DB, "wb") as dst:
        dctx.copy_stream(src, dst)
    print(f"복원 완료: {os.path.getsize(DB)/1024/1024:.1f} MB")


def compress():
    if not os.path.exists(DB):
        print("없음:", DB)
        sys.exit(1)
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    cctx = zstd.ZstdCompressor(level=10, threads=-1)
    with open(DB, "rb") as src, open(ZST, "wb") as dst:
        cctx.copy_stream(src, dst)
    print(f"압축 완료: {os.path.getsize(ZST)/1024/1024:.1f} MB → {ZST}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["compress", "decompress"])
    args = p.parse_args()
    if args.cmd == "compress":
        compress()
    else:
        decompress()
