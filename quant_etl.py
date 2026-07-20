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
    
    try:
        df = pd.read_csv(file_path, encoding='utf-8')
    except UnicodeDecodeError:
        df = pd.read_csv(file_path, encoding='euc-kr')
        
    df['코드'] = df['코드'].astype(str).str.zfill(6)
    
    os.makedirs('data_cache', exist_ok=True)
    db_path = 'data_cache/quant_history.db'
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    company_col = '회사명  (더블클릭시 요약정보)' if '회사명  (더블클릭시 요약정보)' in df.columns else '회사명'
    master_data = df[['코드', company_col, '시장구분', '업종대']].drop_duplicates().values.tolist()
    
    cursor.executemany('''
        INSERT OR IGNORE INTO stock_master (ticker, name, market, sector, is_active)
        VALUES (?, ?, ?, ?, 1)
    ''', master_data)
    
    def safe_get(col_name):
        return df[col_name].fillna(0).tolist() if col_name in df.columns else [0] * len(df)
    
    # 🔥 모멘텀 팩터(1개월, 6개월, 12개월 등락률) 추가 완벽 매핑
    factor_data = list(zip(
        [target_date] * len(df),
        df['코드'].tolist(),
        safe_get('PER'),
        safe_get('PBR'),
        safe_get('PSR'),
        safe_get('EV /EBITDA'),
        safe_get('ROE (%)'),                 
        safe_get('OPM (%)'),
        safe_get('GPM (%)'),
        safe_get('부채 비율 (%)'),
        safe_get('F스코어 점수 (9점만점)'),
        safe_get('1개월 등락률 (%)'),   
        safe_get('6개월 등락률 (%)'),   
        safe_get('1년 등락률 (%)')      
    ))
    
    cursor.executemany('''
        INSERT OR REPLACE INTO monthly_factor 
        (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin, debt_ratio, f_score, mom_1m, mom_6m, mom_12m)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', factor_data)
    
    conn.commit()
    conn.close()
    
    print(f"✅ [성공] 총 {len(df)}개 종목 팩터(모멘텀 포함) 적재 완료!")
    print(f"⏱️ 소요 시간: {time.time() - start_time:.2f}초")

if __name__ == "__main__":
    build_etl_pipeline("Quant_data.csv", "2026-07")
    