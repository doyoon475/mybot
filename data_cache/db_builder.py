import sqlite3
import pandas as pd
import os

# 1. 공통 설정 (경로 및 이번 달 날짜)
save_folder = r"data_cache"
db_file = os.path.join(save_folder, "quant_history.db")

current_date = '2026-07-01'
us_excel_file = os.path.join(save_folder, f"US_AQR_Pro_Edition_{current_date.replace('-', '')}.xlsx")
kr_excel_file = os.path.join(save_folder, "7월_최종_퀀트랭킹.xlsx") 

print("🚀 [통합 DB 빌더] 미국장과 한국장 데이터를 한 번에 DB에 저장합니다...\n")
conn = sqlite3.connect(db_file)

# 2. 미국장 데이터 밀어넣기
try:
    df_us = pd.read_excel(us_excel_file)
    df_us['Date'] = current_date
    df_us.to_sql('us_quant_ranking', conn, if_exists='append', index=False)
    print("✅ [미국장] 'us_quant_ranking' 테이블 저장 완료!")
except FileNotFoundError:
    print(f"❌ [미국장] 엑셀 파일을 찾을 수 없습니다: {us_excel_file}")

# 3. 한국장 데이터 밀어넣기
try:
    df_kr = pd.read_excel(kr_excel_file)
    df_kr['Date'] = current_date
    df_kr.to_sql('kr_quant_ranking', conn, if_exists='append', index=False)
    print("✅ [한국장] 'kr_quant_ranking' 테이블 저장 완료!")
except FileNotFoundError:
    print(f"❌ [한국장] 엑셀 파일을 찾을 수 없습니다: {kr_excel_file}")

conn.close()
print("\n🎉 모든 DB 업데이트 작업이 끝났습니다!")