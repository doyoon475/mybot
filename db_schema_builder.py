import sqlite3
import os

def create_quant_database():
    # DB가 저장될 폴더 생성 (없으면 자동 생성)
    os.makedirs('data_cache', exist_ok=True)
    db_path = 'data_cache/quant_history.db'
    
    # DB 연결 (파일이 없으면 새로 생성됨)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("🚀 [시니어 모드] 초고속 퀀트 데이터베이스 스키마 구축을 시작합니다...")

    # ---------------------------------------------------------
    # 1. 주식 마스터 테이블 (종목 기본 정보 - 변하지 않는 고정 데이터)
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stock_master (
        ticker TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        market TEXT NOT NULL,       -- KOSPI, KOSDAQ, NYSE, NASDAQ 등
        sector TEXT,                -- IT, 금융, 헬스케어 등 섹터 정보
        is_active INTEGER DEFAULT 1 -- 1: 상장, 0: 상장폐지 (생존 편향 방지용)
    )
    ''')

    # ---------------------------------------------------------
    # 2. 일별 주가 테이블 (백테스팅 차트 렌더링용)
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_price (
        date TEXT NOT NULL,
        ticker TEXT NOT NULL,
        close REAL NOT NULL,
        volume REAL,
        PRIMARY KEY (date, ticker),
        FOREIGN KEY (ticker) REFERENCES stock_master(ticker)
    )
    ''')
    # ⚡ [속도 최적화] 특정 종목의 과거 주가를 빠르게 뽑아오기 위한 인덱스
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_daily_price_ticker ON daily_price(ticker)')

    # ---------------------------------------------------------
    # 3. 월별 재무/팩터 테이블 (퀀트킹 데이터 적재 및 필터링용)
    # ---------------------------------------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS monthly_factor (
        date TEXT NOT NULL,         -- 예: 2023-12 (월간 데이터 기준)
        ticker TEXT NOT NULL,
        
        -- 가치(Value) 팩터
        per REAL,
        pbr REAL,
        psr REAL,
        ev_ebitda REAL,
        
        -- 우량(Quality) 팩터
        roe REAL,
        op_margin REAL,             -- 영업이익률
        gross_margin REAL,          -- 매출총이익률 (V5 혁신 지표)
        debt_ratio REAL,            -- 부채비율
        f_score INTEGER,            -- 재무건전성 점수
        
        -- 현금흐름 및 주주환원
        fcf_yield REAL,
        div_yield REAL,
        
        -- 모멘텀(Momentum) 팩터
        mom_1m REAL,
        mom_6m REAL,
        mom_12m REAL,
        earn_mom REAL,              -- 이익 모멘텀(OP/NI YoY %)
        factor_mom REAL,            -- 팩터 모멘텀(런타임 산출 가능)
        
        PRIMARY KEY (date, ticker),
        FOREIGN KEY (ticker) REFERENCES stock_master(ticker)
    )
    ''')
    # 기존 DB 호환: 컬럼 누락 시 추가
    existing = {r[1] for r in cursor.execute("PRAGMA table_info(monthly_factor)")}
    for col, typ in (("earn_mom", "REAL"), ("factor_mom", "REAL"), ("gross_margin", "REAL"), ("f_score", "INTEGER")):
        if col not in existing:
            try:
                cursor.execute(f"ALTER TABLE monthly_factor ADD COLUMN {col} {typ}")
            except Exception:
                pass
    # ⚡ [속도 최적화] 특정 연월(date)의 랭킹을 0.1초 만에 계산하기 위한 인덱스
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_monthly_factor_date ON monthly_factor(date)')

    conn.commit()
    conn.close()
    print("✅ [성공] 'quant_history.db' 내 핵심 테이블(Master, Price, Factor) 및 인덱스 생성이 완료되었습니다.")

if __name__ == "__main__":
    create_quant_database()
    