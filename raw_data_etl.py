import os
import glob
import zipfile
import time
import sqlite3
import pandas as pd
import re
import sys

# stdout 인코딩 설정
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

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

def process_raw_data(skip_existing_months: bool = False, only_recent_files: int = 0):
    """
    skip_existing_months: DB에 이미 있는 YYYY-MM 은 스킵 (일일 자동화용)
    only_recent_files: 0이면 전체, N이면 mtime 기준 최신 N개만 처리
    """
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
    if only_recent_files and only_recent_files > 0:
        data_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        data_files = data_files[:only_recent_files]
    
    if not data_files:
        print("⚠️ 처리할 데이터 파일(.csv, .xlsx)이 존재하지 않습니다.")
        return

    # 대용량 시계열 데이터를 꽂아넣기 위한 초고속 SQLite 세팅
    # database is locked 에러 방지를 위해 timeout을 넉넉히 주고, 
    # 독립적인 연결을 사용하도록 격리합니다.
    conn = sqlite3.connect(db_path, timeout=300.0)
    cursor = conn.cursor()
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA journal_mode = WAL")  # MEMORY 대신 WAL 모드로 변경하여 동시성 개선
    cursor.execute("PRAGMA busy_timeout = 300000")

    existing_months = set()
    if skip_existing_months:
        try:
            existing_months = {
                r[0] for r in cursor.execute("SELECT DISTINCT date FROM monthly_factor").fetchall()
            }
            print(f"📅 DB에 이미 있는 월: {len(existing_months)}개 (해당 월 스킵)")
        except Exception:
            existing_months = set()
    
    total_rows_inserted = 0

    for file_path in data_files:
        filename = os.path.basename(file_path)
        
        # 파일명에서 년월(YYYY-MM) 자동 추출 (예: 퀀트데이터2025.10.01 -> 2025-10)
        date_match = re.search(r'20\d{2}\.\d{2}\.\d{2}', filename)
        if date_match:
            target_month = date_match.group(0)[:7].replace('.', '-')
        else:
            # 서버 저장명(1681...xlsx)은 본문 날짜가 없으므로 mtime 기준 월 사용
            target_month = time.strftime("%Y-%m", time.localtime(os.path.getmtime(file_path)))
            
        if skip_existing_months and target_month in existing_months:
            print(f"⏭️  [{target_month}] 이미 DB에 있음 → 스킵: {filename[:30]}")
            continue

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

        # Column Mapping (엄격한 기준 및 구버전 긴 컬럼명 지원)
        mapped_columns = {}
        for col in df.columns:
            col_str = str(col).strip()
            if col_str == '코드' or '기업코드' in col_str:
                mapped_columns[col] = 'ticker'
            elif col_str == '회사명' or '회사이름' in col_str or '회사명  (더블클릭시 요약정보)' in col_str:
                mapped_columns[col] = 'name'
            elif col_str == 'PER' or col_str.startswith('PER='):
                mapped_columns[col] = 'per'
            elif col_str == 'PBR' or col_str.startswith('PBR='):
                mapped_columns[col] = 'pbr'
            elif col_str == 'PSR' or col_str.startswith('PSR='):
                mapped_columns[col] = 'psr'
            elif col_str == 'EV /EBITDA' or col_str.startswith('EV/EBITDA='):
                mapped_columns[col] = 'ev_ebitda'
            elif col_str == 'ROE (%)' or col_str.startswith('ROE='):
                mapped_columns[col] = 'roe'
            elif col_str == 'OPM (%)' or col_str.startswith('OPM='):
                mapped_columns[col] = 'op_margin'
            elif col_str == 'GPM (%)' or col_str.startswith('GPM='):
                mapped_columns[col] = 'gross_margin'
            elif col_str == '부채 비율 (%)' or col_str.startswith('부채비율='):
                mapped_columns[col] = 'debt_ratio'
            elif col_str == 'F스코어 점수 (9점만점)' or '포인트점수키' in col_str or 'F-Score' in col_str:
                mapped_columns[col] = 'f_score'
            elif col_str == '1개월 등락률 (%)' or '1개월전 수정주가' in col_str:
                mapped_columns[col] = 'mom_1m'
            elif col_str == '6개월 등락률 (%)' or '6개월전 수정주가' in col_str:
                mapped_columns[col] = 'mom_6m'
            elif col_str == '1년 등락률 (%)' or '1년전 수정주가' in col_str:
                mapped_columns[col] = 'mom_12m'
            else:
                mapped_columns[col] = col
                
        df.rename(columns=mapped_columns, inplace=True)
        
        # 🚨 [시니어 최적화] "PerformanceWarning: DataFrame is highly fragmented" 경고 해결
        # Pandas가 열(Column)을 여러 번 수정/추가하다가 내부 메모리 구조가 파편화되는 현상 방지
        # 한 번 복사(copy)를 떠서 메모리를 연속적으로 깔끔하게 재배치해 줌
        df = df.copy()
        
        # Ticker 및 Date 포맷팅 (daily_price와 동일하게 A+6자리)
        if 'ticker' in df.columns:
            t = df['ticker'].astype(str).str.strip()
        elif '코드' in df.columns:
            t = df['코드'].astype(str).str.strip()
        else:
            print(f"  ⚠️ 티커 컬럼 없음 → 스킵: {filename[:40]}")
            continue
        digits = t.str.replace(r'^A', '', regex=True).str.replace(r'\D', '', regex=True).str.zfill(6).str[-6:]
        df['ticker'] = 'A' + digits
        df = df[df['ticker'].str.match(r'^A\d{6}$', na=False)].copy()
            
        df['date'] = target_month
        
        # DB 삽입용 필수 컬럼 방어 코드 (없으면 0.0 처리)
        insert_cols = ['date', 'ticker', 'per', 'pbr', 'psr', 'ev_ebitda', 'roe', 'op_margin', 'gross_margin', 'debt_ratio', 'f_score', 'mom_1m', 'mom_6m', 'mom_12m']
        missing_cols = {col: 0.0 for col in insert_cols if col not in df.columns}
        if missing_cols:
            df = df.assign(**missing_cols)
                
        # NaN 처리 및 튜플 변환 (문자열 컬럼에 0이 들어가는 에러 방지)
        for col in df.columns:
            if df[col].dtype == 'object' or pd.api.types.is_string_dtype(df[col]):
                df[col] = df[col].fillna("")
            else:
                df[col] = df[col].fillna(0.0)
                
        insert_data = list(zip(
            df['date'], df['ticker'], df['per'], df['pbr'], df['psr'], df['ev_ebitda'], 
            df['roe'], df['op_margin'], df['gross_margin'], df['debt_ratio'], 
            df['f_score'], df['mom_1m'], df['mom_6m'], df['mom_12m']
        ))
        
        # 고속 병합 삽입
        retry_count = 0
        while retry_count < 3:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor.executemany('''
                    INSERT OR REPLACE INTO monthly_factor 
                    (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin, debt_ratio, f_score, mom_1m, mom_6m, mom_12m)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', insert_data)
                conn.commit()  # 매 파일마다 커밋하여 lock 방지
                break # 성공 시 루프 탈출
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    retry_count += 1
                    print(f"  ⚠️ DB Lock 발생. 재시도 중... ({retry_count}/3)")
                    conn.rollback()
                    time.sleep(5) # 대기 시간 대폭 증가
                else:
                    print(f"  ❌ DB Insert 에러: {e}")
                    conn.rollback()
                    break
            except Exception as e:
                print(f"  ❌ DB Insert 에러: {e}")
                conn.rollback()
                break
        
        total_rows_inserted += len(insert_data)

    # 확정 및 닫기
    try:
        conn.commit()
    except:
        pass
    conn.close()
    
    print(f"\n✅ [성공] 총 {total_rows_inserted:,}행의 팩터 데이터 적재 완료!")
    print(f"⏱️ 소요 시간: {time.time() - start_time:.2f}초")

if __name__ == "__main__":
    process_raw_data()
