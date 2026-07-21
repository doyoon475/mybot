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


def extract_target_month(filename: str, file_path: str = "") -> str:
    """
    1) 파일명 2023.04.11 형태
    2) 퀀트킹 서버명 1681220469_1.xlsx (unix timestamp = 게시일)
    3) mtime (다운로드 시각 — 과거 소급에 부적합, 최후 수단)
    """
    date_match = re.search(r"20\d{2}\.\d{2}\.\d{2}", filename)
    if date_match:
        return date_match.group(0)[:7].replace(".", "-")

    ts_match = re.match(r"^(\d{9,10})_\d+\.(xlsx|xls|csv)$", filename, re.I)
    if ts_match:
        try:
            from datetime import datetime
            return datetime.fromtimestamp(int(ts_match.group(1))).strftime("%Y-%m")
        except Exception:
            pass

    if file_path and os.path.exists(file_path):
        return time.strftime("%Y-%m", time.localtime(os.path.getmtime(file_path)))
    return "1900-01"


def _norm_col(col) -> str:
    return str(col).replace("\n", " ").replace("\r", " ").strip()


def read_quant_table(file_path: str) -> pd.DataFrame:
    """구버전(상단 안내문 2~3행) / 신버전 엑셀 모두 헤더 자동 탐지."""
    if file_path.lower().endswith(".csv"):
        try:
            df = pd.read_csv(file_path, encoding="utf-8", low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding="euc-kr", low_memory=False)
        df.columns = [_norm_col(c) for c in df.columns]
        return df

    raw = pd.read_excel(file_path, header=None)
    header_row = 0
    for i in range(min(12, len(raw))):
        row_txt = " ".join(_norm_col(v) for v in raw.iloc[i].tolist())
        if "코드" in row_txt and ("회사" in row_txt or "시가총액" in row_txt or "PER" in row_txt):
            header_row = i
            break
    df = pd.read_excel(file_path, header=header_row)
    df.columns = [_norm_col(c) for c in df.columns]
    # 완전 빈 열 제거
    df = df.dropna(axis=1, how="all")
    return df


def map_factor_columns(df: pd.DataFrame) -> pd.DataFrame:
    """신·구 퀀트킹 컬럼명을 monthly_factor 표준명으로 매핑."""
    # 우선순위 후보 (앞에 있을수록 선호) — 나중에 나온 동일 표준명은 덮어쓰지 않음
    preferences = {
        "ticker": ["코드", "코드 번호", "기업코드"],
        "name": ["회사명", "회사이름", "회사명  (더블클릭시 요약정보)"],
        "per": [
            "PER", "발표 PER", "올해 PER", "선행 PER", "현재 PER",
            "후행 PER", "1년후 PER", "과거 PER",
        ],
        "pbr": [
            "PBR", "발표 PBR", "선행 PBR", "현재 PBR", "목표 PBR",
            "1년후 PBR", "과거 PBR",
        ],
        "psr": ["PSR", "발표 PSR", "선행 PSR", "목표 PSR", "과거 PSR"],
        "ev_ebitda": [
            "EV /EBITDA", "EV/EBITDA", "과거 EV/EBITDA (%)",
            "선행 EV/EBITDA (%)", "선행 EV/EBITDA",
        ],
        "roe": [
            "ROE (%)", "과거 ROE (%)", "선행 ROE (%)", "ROE",
            "1년후 ROE (%)", "1개월 ROE (%)",
        ],
        "op_margin": [
            "OPM (%)", "발표 OPM (%)", "올해 OPM (%)",
            "선행 OPM (%)", "목표 OPM (%)", "OPM",
        ],
        "gross_margin": ["GPM (%)", "과거 GPM (%)", "선행 GPM (%)", "GPM"],
        "debt_ratio": [
            "부채 비율 (%)", "연결 부채비율 (%)", "단순 부채비율 (%)", "부채비율",
        ],
        "f_score": [
            "F스코어 점수 (9점만점)", "F-Score", "F스코어",
            "* 피오트로스키: F-Score라고 도함",
        ],
        "mom_1m": [
            "1개월 등락률 (%)", "1개월 등락율 (%)",
            "(현재가 - 1개월전 수정주가)*100/1개월전 수정주가",
        ],
        "mom_6m": [
            "6개월 등락률 (%)", "6개월 등락율 (%)",
            "(현재가 - 6개월전 수정주가)*100/6개월전 수정주가",
        ],
        "mom_12m": [
            "1년 등락률 (%)", "1년 등락율 (%)",
            "(현재가 - 1년전 수정주가)*100/1년전 수정주가",
        ],
        "earn_mom": [
            "최근 연환산 영업이익의 전년동기대비 증가율",
            "해당년도 영업이익의 전년동기대비 증가율",
            "해당분기 영업이익의 전년동기대비 증가율",
            "최근 연환산 지배순이익의 전년동기대비 증가율",
            "해당분기 예상 영업이익의 전년동기대비 증가율",
            "해당분기 예상 영업이익의 전년동기대비 증가율. 실적 발표시 발표치 반영됨.",
        ],
        # Phase B5: 다년 성장 (신·구 헤더 병행)
        "sales_g3y": ["직전년도 매출액의 3년전대비 증가율"],
        "op_g3y": ["직전년도 영업이익의 3년전대비 증가율"],
        "ni_g3y": ["직전년도 지배순이익의 3년전대비 증가율"],
        # Phase B6: 배당·희석
        "div_yield": ["시가 배당률 (%)", "시가 배당율 (%)"],
        "share_growth": ["주식수 증가율 (%)"],
        # Phase B7: 자사주
        "treasury_pct": ["자사주 비중 (%)"],
        "treasury_chg": [],
    }

    cols = list(df.columns)
    rename = {}
    used_src = set()

    for std, cands in preferences.items():
        # 1) 정확 일치
        for cand in cands:
            if cand in cols and cand not in used_src:
                rename[cand] = std
                used_src.add(cand)
                break
        if std in rename.values():
            continue
        # 2) 느슨한 매칭
        for col in cols:
            if col in used_src:
                continue
            if std == "ticker" and (col.startswith("코드") or "기업코드" in col):
                rename[col] = std
                used_src.add(col)
                break
            if std == "name" and ("회사명" in col or "회사이름" in col):
                rename[col] = std
                used_src.add(col)
                break
            if std == "f_score" and (
                "F스코어 점수" in col
                or "F-Score" in col
                or "피오트로스키" in col
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "mom_1m" and "1개월전 수정주가" in col and "현재가" in col:
                rename[col] = std
                used_src.add(col)
                break
            if std == "mom_6m" and "6개월전 수정주가" in col and "현재가" in col:
                rename[col] = std
                used_src.add(col)
                break
            if std == "mom_12m" and "1년전 수정주가" in col and "현재가" in col:
                rename[col] = std
                used_src.add(col)
                break
            if std == "earn_mom" and (
                ("영업이익" in col or "지배순이익" in col or "EPS" in col)
                and "전년" in col
                and "증가" in col
                and "3년전" not in col
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "sales_g3y" and "매출액" in col and (
                ("3년전" in col and "증가" in col) or "3년간 YOY" in col
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "op_g3y" and "영업이익" in col and (
                ("3년전" in col and "증가" in col) or "3년간 YOY" in col
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "ni_g3y" and (
                ("지배순이익" in col or (col.startswith("순이익") and "EPS" not in col))
                and (("3년전" in col and "증가" in col) or "3년간 YOY" in col)
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "div_yield" and (
                col.startswith("연간배당률=")
                or (("시가" in col) and ("배당률" in col or "배당율" in col) and "고점" not in col and "저점" not in col and "국채" not in col)
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "share_growth" and (
                ("보통주 수정주식수" in col and "1년전" in col and "현재" in col)
                or col == "주식수 증가율 (%)"
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "treasury_pct" and (
                col == "자사주 비중 (%)"
                or ("자사주" in col and "상장주식수" in col and "100" in col)
            ):
                rename[col] = std
                used_src.add(col)
                break
            if std == "treasury_chg" and (
                "자사주비중" in col
                and "1년전" in col
                and "현재" in col
                and "3개월" not in col
            ):
                rename[col] = std
                used_src.add(col)
                break

    # 2019~2020: 라벨 없는 "NN년->NN년 3년간 YOY" / .1 / .2 = 매출/영업/순이익 순서
    if not {"sales_g3y", "op_g3y", "ni_g3y"}.issubset(set(rename.values())):
        legacy = []
        for col in cols:
            if col in used_src:
                continue
            m = re.fullmatch(r"(\d+년->\d+년 3년간 YOY)(?:\.(\d+))?", col)
            if m:
                legacy.append((m.group(1), int(m.group(2) or 0), col))
        legacy.sort(key=lambda x: (x[0], x[1]))
        for std, item in zip(("sales_g3y", "op_g3y", "ni_g3y"), legacy[:3]):
            if std in rename.values():
                continue
            col = item[2]
            rename[col] = std
            used_src.add(col)

    # PER=... 형태 (신버전)
    for col in cols:
        if col in used_src:
            continue
        if col.startswith("PER=") and "per" not in rename.values():
            rename[col] = "per"
            used_src.add(col)
        elif col.startswith("PBR=") and "pbr" not in rename.values():
            rename[col] = "pbr"
            used_src.add(col)
        elif col.startswith("PSR=") and "psr" not in rename.values():
            rename[col] = "psr"
            used_src.add(col)
        elif col.startswith("ROE=") and "roe" not in rename.values():
            rename[col] = "roe"
            used_src.add(col)
        elif col.startswith("OPM=") and "op_margin" not in rename.values():
            rename[col] = "op_margin"
            used_src.add(col)
        elif col.startswith("GPM=") and "gross_margin" not in rename.values():
            rename[col] = "gross_margin"
            used_src.add(col)
        elif col.startswith("부채비율=") and "debt_ratio" not in rename.values():
            rename[col] = "debt_ratio"
            used_src.add(col)
        elif col.startswith("EV/EBITDA=") and "ev_ebitda" not in rename.values():
            rename[col] = "ev_ebitda"
            used_src.add(col)
        elif col.startswith("연간배당률=") and "div_yield" not in rename.values():
            rename[col] = "div_yield"
            used_src.add(col)

    out = df.rename(columns=rename)
    return out


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

    # earn_mom 컬럼 보장
    try:
        from factor_builder import ensure_factor_columns
        ensure_factor_columns(conn)
        conn.commit()
    except Exception as e:
        print(f"⚠️ 컬럼 마이그레이션 경고: {e}")

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
        target_month = extract_target_month(filename, file_path)
            
        if skip_existing_months and target_month in existing_months:
            print(f"⏭️  [{target_month}] 이미 DB에 있음 → 스킵: {filename[:30]}")
            continue

        print(f"🔄 [{target_month}] 파일 변환 및 적재 중: {filename[:30]}...")
            
        try:
            df = read_quant_table(file_path)
            df = map_factor_columns(df)
        except Exception as e:
            print(f"  ❌ 파일 읽기 에러: {e}")
            continue
        
        # 🚨 [시니어 최적화] "PerformanceWarning: DataFrame is highly fragmented" 경고 해결
        df = df.copy()
        
        # Ticker 및 Date 포맷팅 (daily_price와 동일하게 A+6자리)
        if "ticker" in df.columns:
            t = df["ticker"].astype(str).str.strip()
        else:
            # 최후: A###### 패턴 컬럼 자동 탐색
            t = None
            for col in df.columns:
                sample = df[col].astype(str).head(20)
                if sample.str.contains(r"^A?\d{6}$", regex=True, na=False).sum() >= 5:
                    t = df[col].astype(str).str.strip()
                    print(f"  ℹ️ 티커 컬럼 자동감지: {col}")
                    break
            if t is None:
                print(f"  ⚠️ 티커 컬럼 없음 → 스킵: {filename[:40]}")
                continue
        digits = t.str.replace(r"^A", "", regex=True).str.replace(r"\D", "", regex=True).str.zfill(6).str[-6:]
        df["ticker"] = "A" + digits
        df = df[df['ticker'].str.match(r'^A\d{6}$', na=False)].copy()
            
        df['date'] = target_month
        
        # DB 삽입: 없는 팩터 컬럼은 NaN 유지 (0.0으로 채우면 랭킹 왜곡)
        insert_cols = [
            "date", "ticker", "per", "pbr", "psr", "ev_ebitda", "roe", "op_margin",
            "gross_margin", "debt_ratio", "f_score", "mom_1m", "mom_6m", "mom_12m",
            "earn_mom", "sales_g3y", "op_g3y", "ni_g3y", "growth_stab",
            "div_yield", "share_growth", "treasury_pct", "treasury_chg",
        ]
        for col in insert_cols:
            if col not in df.columns:
                df[col] = float("nan")
            elif col not in ("date", "ticker"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
                # 가치 멀티플 0 이하는 NULL (랭킹 왜곡 방지)
                if col in ("per", "pbr", "psr", "ev_ebitda"):
                    df.loc[df[col] <= 0, col] = float("nan")
                if col in ("mom_1m", "mom_6m", "mom_12m"):
                    df.loc[df[col] <= -99.9, col] = float("nan")
                if col == "div_yield":
                    df.loc[df[col] <= 0, col] = float("nan")

        try:
            from factor_extras import compute_growth_stab
            df["growth_stab"] = compute_growth_stab(df)
        except Exception:
            df["growth_stab"] = float("nan")


        # 문자열 컬럼만 빈문자, 팩터는 NaN 유지 → SQLite NULL
        if "name" in df.columns:
            df["name"] = df["name"].fillna("")
                
        insert_data = []
        def _nullify(v):
            if v is None:
                return None
            try:
                if pd.isna(v):
                    return None
            except Exception:
                pass
            return v

        insert_data = [
            tuple(_nullify(v) for v in vals)
            for vals in df[insert_cols].itertuples(index=False, name=None)
        ]
        
        # 고속 병합 삽입
        retry_count = 0
        while retry_count < 3:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor.executemany('''
                    INSERT OR REPLACE INTO monthly_factor 
                    (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin,
                     debt_ratio, f_score, mom_1m, mom_6m, mom_12m, earn_mom,
                     sales_g3y, op_g3y, ni_g3y, growth_stab, div_yield, share_growth,
                     treasury_pct, treasury_chg)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
