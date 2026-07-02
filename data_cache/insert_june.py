import sqlite3
import pandas as pd
import os

save_folder = r"C:\mybot\data_cache"
db_file = os.path.join(save_folder, "quant_history.db")
csv_file = os.path.join(save_folder, "AQR_Pro_Edition_20260617_234830.csv")

print("🔄 [안전 모드] 6월 17일 데이터를 DB 창고에 적재하는 중...\n")

if not os.path.exists(csv_file):
    print(f"❌ CSV 파일을 찾을 수 없습니다! 경로를 확인해주세요: {csv_file}")
    exit()

# 인코딩 예외 처리하며 안전하게 파일 읽기
try:
    df = pd.read_csv(csv_file, encoding='utf-8-sig')
except:
    df = pd.read_csv(csv_file, encoding='cp949')

# 📅 과거 날짜 도장 생성
df['Date'] = '2026-06-17'

# 💡 팩터명 유연한 매핑 시스템 가동 (괄호 및 공백 변수 제거)
rename_dict = {}
for col in df.columns:
    if "종목명" in col: rename_dict[col] = "종목명"
    elif "최종" in col: rename_dict[col] = "최종점수"
    elif "가치" in col: rename_dict[col] = "가치점수"
    elif "우량" in col: rename_dict[col] = "우량점수"
    elif "모멘텀" in col: rename_dict[col] = "모멘텀점수"
    elif "샤프" in col: rename_dict[col] = "샤프지수"
    elif "거래대금" in col: rename_dict[col] = "거래대금(억)"

df = df.rename(columns=rename_dict)
table_name = 'kr_quant_ranking' if '종목명' in df.columns else 'us_quant_ranking'

# 🔒 대시보드가 켜져 있어도 락(Lock)에 걸리지 않도록 30초 대기 옵션 추가
conn = sqlite3.connect(db_file, timeout=30)

try:
    # DB 구조를 직접 뜯어보고 컬럼 리스트 확보
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    db_actual_cols = [row[1] for row in cursor.fetchall()]
    
    if not db_actual_cols:
        # 테이블이 비어있거나 없는 경우 예외 처리
        df.to_sql(table_name, conn, if_exists='append', index=False)
    else:
        # 실제 DB에 존재하는 컬럼 명단과 교집합인 데이터만 안전하게 필터링
        matched_cols = [col for col in db_actual_cols if col in df.columns]
        df_final = df[matched_cols]
        
        # 최후의 적재 감행
        df_final.to_sql(table_name, conn, if_exists='append', index=False)
        
    print(f"\n✅ 성공! 6월 17일 데이터가 '{table_name}' 테이블에 안전하게 병합되었습니다.")

except Exception as error:
    print(f"\n❌ 실패! 시스템 보호 오류가 발생했습니다: {error}")
    print("💡 웹 대시보드가 실행 중이라면 잠시 대시보드를 끈 후 다시 시도해보세요.")

finally:
    conn.close()