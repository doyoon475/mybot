import os
import sqlite3
import urllib.request
import json
import time
from dotenv import load_dotenv

# ==========================================
# Turso HTTP API 마이그레이션 스크립트 (의존성 최소화)
# ==========================================
load_dotenv()
TURSO_DB_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

def run_query(sql, args=None):
    if not TURSO_DB_URL or not TURSO_AUTH_TOKEN:
        print("❌ .env 파일에 TURSO_DATABASE_URL 또는 TURSO_AUTH_TOKEN이 없습니다.")
        return None
        
    # libsql:// 이나 wss:// 로 시작하면 https:// 로 변경
    base_url = TURSO_DB_URL.replace("libsql://", "https://").replace("wss://", "https://")
    url = f"{base_url}/v2/pipeline"
    
    headers = {
        "Authorization": f"Bearer {TURSO_AUTH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    stmt = {"sql": sql}
    if args:
        # Turso HTTP API는 인자를 엄격한 타입으로 요구함 (integer, float, text)
        formatted_args = []
        for arg in args:
            if isinstance(arg, int):
                # 정수는 JSON 64비트 호환성을 위해 문자열로 쏴야 함
                formatted_args.append({"type": "integer", "value": str(arg)})
            elif isinstance(arg, float):
                # 🚨 핵심: 소수는 문자열("17.89")이 아니라 순수 숫자형(17.89) 그대로 쏴야 함!
                formatted_args.append({"type": "float", "value": float(arg)})
            elif arg is None:
                formatted_args.append({"type": "null"})
            else:
                formatted_args.append({"type": "text", "value": str(arg)})
        stmt["args"] = formatted_args
        
    payload = {
        "requests": [
            {"type": "execute", "stmt": stmt},
            {"type": "close"}
        ]
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            return res
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP API 에러: {e.code} - {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"❌ 요청 에러: {e}")
        return None

def migrate_to_turso():
    print("🚀 [클라우드 마이그레이션] 로컬 SQLite -> Turso DB 테이블 복사 시작...")
    
    # 1. 테이블 생성 (스키마 복사)
    print("📦 클라우드에 테이블 스키마 생성 중...")
    schema_queries = [
        """
        CREATE TABLE IF NOT EXISTS stock_master (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            market TEXT,
            sector TEXT,
            is_active INTEGER DEFAULT 1
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS monthly_factor (
            date TEXT,
            ticker TEXT,
            per NUMERIC,
            pbr NUMERIC,
            psr NUMERIC,
            ev_ebitda NUMERIC,
            roe NUMERIC,
            op_margin NUMERIC,
            gross_margin NUMERIC,
            debt_ratio NUMERIC,
            f_score NUMERIC,
            mom_1m NUMERIC,
            mom_6m NUMERIC,
            mom_12m NUMERIC,
            PRIMARY KEY (date, ticker)
        )
        """
    ]
    
    for q in schema_queries:
        run_query(q)
        time.sleep(0.5)
        
    print("✅ 테이블 생성 완료!")
    
    # 2. stock_master 데이터 밀어넣기
    print("\n📦 로컬 DB에서 stock_master 읽어오는 중...")
    local_conn = sqlite3.connect("data_cache/quant_history.db")
    local_cur = local_conn.cursor()
    
    local_cur.execute("SELECT ticker, name, market, sector, is_active FROM stock_master")
    master_rows = local_cur.fetchall()
    print(f"총 {len(master_rows)}개의 종목 정보를 클라우드로 전송합니다.")
    
    for i, row in enumerate(master_rows):
        sql = "INSERT OR IGNORE INTO stock_master (ticker, name, market, sector, is_active) VALUES (?, ?, ?, ?, ?)"
        run_query(sql, row)
        if (i+1) % 500 == 0:
            print(f"  ... {i+1}개 완료")
            
    # 3. monthly_factor 데이터 밀어넣기 (최신 1개월치만)
    print("\n📦 로컬 DB에서 monthly_factor 읽어오는 중...")
    local_cur.execute("SELECT date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin, debt_ratio, f_score, mom_1m, mom_6m, mom_12m FROM monthly_factor")
    factor_rows = local_cur.fetchall()
    print(f"총 {len(factor_rows)}개의 팩터 데이터를 클라우드로 전송합니다. (시간이 다소 소요될 수 있습니다)")
    
    for i, row in enumerate(factor_rows):
        sql = """
            INSERT OR REPLACE INTO monthly_factor 
            (date, ticker, per, pbr, psr, ev_ebitda, roe, op_margin, gross_margin, debt_ratio, f_score, mom_1m, mom_6m, mom_12m) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        run_query(sql, row)
        if (i+1) % 500 == 0:
            print(f"  ... {i+1}개 완료")
            
    print("\n🎉 클라우드 마이그레이션이 성공적으로 완료되었습니다!")

if __name__ == "__main__":
    migrate_to_turso()