import os
import glob
import zipfile
import time
import sqlite3
import pandas as pd
import re

# ==========================================
# 엄격한 회계 및 조세 실무 기준 COLUMN MAPPING 룰
# (시니어의 철학: 재무제표의 변동성/다양한 명칭을 하나의 표준 팩터로 통일)
# ==========================================
COLUMN_MAPPING = {
    '코드': 'ticker',
    '회사명': 'name',
    
    # 1. 수익성 및 손익계산서 지표 (엄격한 기준 적용)
    '지배주주순이익': ['지배주주순이익', '당기순이익(지배)', '지배지분순이익', '연결지배순이익'],
    '포괄손익': ['포괄손익', '총포괄손익', '당기총포괄손익'],
    '법인세비용차감전순이익': ['법인세비용차감전순이익', '세전계속사업이익', '법인세차감전순이익', '세전이익'],
    
    # 2. 핵심 퀀트 팩터 지표
    'PER': 'per',
    'PBR': 'pbr',
    'PSR': 'psr',
    'EV /EBITDA': 'ev_ebitda',
    'ROE (%)': 'roe',
    'OPM (%)': 'op_margin',
    'GPM (%)': 'gross_margin',
    '부채 비율 (%)': 'debt_ratio',
    'F스코어 점수 (9점만점)': 'f_score',
    '1개월 등락률 (%)': 'mom_1m',
    '6개월 등락률 (%)': 'mom_6m',
    '1년 등락률 (%)': 'mom_12m'
}

def process_raw_data():
    raw_dir = os.path.abspath("./quant_raw_data")
    db_path = os.path.abspath("./data_cache/quant_history.db")
    
    print(f"🚀 [ETL 파이프라인] 대용량 Raw 데이터 변환 및 고속 적재 시작")
    start_time = time.time()
    
    if not os.path.exists(raw_dir):
        os.makedirs(raw_dir, exist_ok=True)
    
    # ---------------------------------------------------------
    # 단계 1: Extract (ZIP 파일 자동 압축 해제 및 원본 청소)
    # ---------------------------------------------------------
    zip_files = glob.glob(os.path.join(raw_dir, "*.zip"))
    for zip_path in zip_files:
        try:
            print(f"📦 압축 해제 중: {os.path.basename(zip_path)}")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(raw_dir)
            os.remove(zip_path) # 공간 확보를 위해 원본 ZIP 즉시 삭제
        except Exception as e:
            print(f"❌ 압축 해제 에러 ({os.path.basename(zip_path)}): {e}")

    # ---------------------------------------------------------
    # 단계 2 & 3: Transform & Load (데이터 정제 및 DB 초고속 적재)
    # ---------------------------------------------------------
    data_files = glob.glob(os.path.join(raw_dir, "*.csv")) + glob.glob(os.path.join(raw_dir, "*.xlsx"))
    
    if not data_files:
        print("⚠️ 처리할 데이터 파일(.csv, .xlsx)이 존재하지 않습니다.")
        return

    # 대용량 시계열 데이터를 꽂아넣기 위한 초고속 SQLite 세팅
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = OFF")
    cursor.execute("PRAGMA journal_mode = MEMORY")
    
    total_rows_inserted = 0

    for file_path in data_files:
        filename = os.path.basename(file_path)
        
        # 파일명에서 년월(YYYY-MM) 자동 추출 (예: 퀀트데이터2025.10.01 -> 2025-10)
        date_match = re.search(r'20\d{2}\.\d{2}\.\d{2}', filename)
        if date_match:
            target_month = date_match.group(0)[:7].replace('.', '-')
        else:
            target_month = "1900-01" # 파싱 실패 시 예외 처리
            
        print(f"🔄 [{target_month}] 파일 변환 및 적재 중: {filename[:30]}...")
            
        try:
            if file_path.endswith('.csv'):
                try:
                    df = pd.read_csv(file_path, encoding='utf-8', low_memory=False)
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, encoding='euc-kr', low_memory=False)
            else:
                df = pd.read_excel(file_path)
        except Exception as e:
            print(f"  ❌ 파일 읽기 에러: {e}")
            continue

        # Column Mapping (엄격한 기준 적용)
        mapped_columns = {}
        for col in df.columns:
            mapped = False
            for target_key, alias_list in COLUMN_MAPPING.items():
                if isinstance(alias_list, list):
                    if col in alias_list:
                        mapped_columns[col] = target_key
                        mapped = True
                        break
                else:
                    if col == target_key or col == alias_list:
                        mapped_columns[col] = alias_list
                        mapped = True
                        break
            if not mapped:
                mapped_columns[col] = col
                
        df.rename(columns=mapped_columns, inplace=True)
        
        # Ticker 및 Date 포맷팅
        if 'ticker' in df.columns:
            df['ticker'] = df['ticker'].astype(str).str.zfill(6)
        elif '코드' in df.columns:
            df['ticker'] = df['코드'].astype(str).str.zfill(6)
            
        df['date'] = target_month
        
        # DB 삽입용 필수 컬럼 방어 코드 (없으면 0.0 처리)
        insert_cols = ['date', 'ticker', 'per', 'pbr', 'psr', 'ev_ebitda', 'roe', 'op_margin', 'gross_margin', 'debt_ratio', 'f_score', 'mom_1m', 'mom_6m', 'mom_12m']
        for col in insert_cols:
            if col not in df.columns:
                df[col] = 0.0
                
        # NaN 처리 및 튜플 변환
        df.fillna(0, inplace=True)
        insert_data = list(zip(
            df['date'], df['ticker'], df['per'], df['pbr'], df['psr'], df['ev_ebitda'], 
            df['roe'], df['op_margin'], df['gross_margin'], df['debt_ratio'], 
            df['f_score'], df['mom_1m'], df['mom_6m'], df['mom_12m']
        ))
        
        # 고속 병합 삽입
        cursor.executemany('''
            INSERT OR REPLACE INTO monthly_factor 
            (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin, debt_ratio, f_score, mom_1m, mom_6m, mom_12m)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', insert_data)
        
        total_rows_inserted += len(insert_data)

    # 확정 및 닫기
    conn.commit()
    conn.close()
    
    print(f"\n✅ [성공] 총 {total_rows_inserted:,}행의 팩터 데이터 적재 완료!")
    print(f"⏱️ 소요 시간: {time.time() - start_time:.2f}초")

if __name__ == "__main__":
    process_raw_data()
