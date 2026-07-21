"""unix timestamp 파일명(1559..._1.xlsx)만 ETL — 2019~2023 소급 적재용"""
import glob
import os
import re
import sys

# raw_data_etl 의 process 를 파일 리스트로 제한하기 위해 임시 래핑
import raw_data_etl as etl

raw = os.path.abspath("./quant_raw_data")
files = [
    p for p in glob.glob(os.path.join(raw, "*.xlsx"))
    if re.match(r"^\d{9,10}_\d+\.xlsx$", os.path.basename(p), re.I)
]
files.sort()
print(f"타임스탬프 파일 {len(files)}개 ETL 시작")

# process_raw_data 가 glob 전체를 쓰므로, 해당 함수를 살짝 우회:
# only_recent 로는 불가 → monkeypatch glob 결과
_orig_glob = glob.glob

def _filtered_glob(pattern, *args, **kwargs):
    res = _orig_glob(pattern, *args, **kwargs)
    if pattern.endswith("*.xlsx") or pattern.endswith("*.csv"):
        return [
            p for p in res
            if re.match(r"^\d{9,10}_\d+\.(xlsx|csv)$", os.path.basename(p), re.I)
        ]
    return res

glob.glob = _filtered_glob
etl.glob.glob = _filtered_glob

try:
    etl.process_raw_data(skip_existing_months=False, only_recent_files=0)
finally:
    glob.glob = _orig_glob
    etl.glob.glob = _orig_glob
