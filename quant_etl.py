import sqlite3
import pandas as pd
import os
import time

def build_etl_pipeline(file_path, target_date):
    print(f"🚀 [ETL 파이프라인] 퀀트킹 데이터({target_date}) 고속 적재 시작...")
    start_time = time.time()
    
    if not os.path.exists(file_path):
        print(f"❌ 에러: '{file_path}' 파일을 찾을 수 없습니다.")
        return
    
    # 1. 데이터 로드 (인코딩 방어 로직)
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='euc-kr')
        
    # 2. 종목코드 6자리 포맷팅
    df['코드'] = df['코드'].astype(str).str.zfill(6)
    
    # 3. SQLite 연결
    os.makedirs('data_cache', exist_ok=True)
    db_path = 'data_cache/quant_history.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # ==========================================
    # [Step 1] stock_master 테이블 고속 병합
    # ==========================================
    # 실제 다운로드된 파일의 괴랄한 컬럼명을 정확히 매핑
    company_col = '회사명  (더블클릭시 요약정보)' if '회사명  (더블클릭시 요약정보)' in df.columns else '회사명'
    
    master_data = df[['코드', company_col, '시장구분', '업종대']].drop_duplicates().values.tolist()
    
    cursor.executemany('''
        INSERT OR IGNORE INTO stock_master (ticker, name, market, sector, is_active)
        VALUES (?, ?, ?, ?, 1)
    ''', master_data)
    
    # ==========================================
    # [Step 2] monthly_factor 테이블 고속 적재
    # ==========================================
    def safe_get(col_name):
        return df[col_name].fillna(0).tolist() if col_name in df.columns else [0] * len(df)
    
    factor_data = list(zip(
        [target_date] * len(df),
        df['코드'].tolist(),
        safe_get('PER'),
        safe_get('PBR'),
        safe_get('PSR'),
        safe_get('EV /EBITDA'),              # 띄어쓰기 주의
        safe_get('ROE (%)'),                 
        safe_get('OPM (%)'),                 # 영업이익률 매핑
        safe_get('GPM (%)'),                 # 매출총이익률 매핑
        safe_get('부채 비율 (%)'),             # 띄어쓰기 주의
        safe_get('F스코어 점수 (9점만점)')       # 명칭 완벽 매핑
    ))
    
    cursor.executemany('''
        INSERT OR REPLACE INTO monthly_factor 
        (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin, debt_ratio, f_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', factor_data)
    
    conn.commit()
    conn.close()
    
    print(f"✅ [성공] 총 {len(df)}개 종목 팩터 적재 완료!")
    print(f"⏱️ 소요 시간: {time.time() - start_time:.2f}초")

if __name__ == "__main__":
    # 다운받은 파일명에 맞게 실행
    build_etl_pipeline("Quant_data.csv", "2026-07")
    