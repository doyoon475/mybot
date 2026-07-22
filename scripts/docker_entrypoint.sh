#!/bin/sh
set -eu

mkdir -p /app/data_cache

if [ ! -f /app/data_cache/quant_history.db ]; then
  echo "[warn] data_cache/quant_history.db 없음 — 볼륨에 DB를 마운트하거나"
  echo "       호스트에서 python pull_db_release.py 후 다시 실행하세요."
fi

# users.db 는 최초 로그인 시 자동 생성
exec streamlit run dashboard_v2.py \
  --server.address=0.0.0.0 \
  --server.port=8501 \
  --browser.gatherUsageStats=false
