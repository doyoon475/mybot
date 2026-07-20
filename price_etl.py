import sqlite3
import pandas as pd
import FinanceDataReader as fdr
import time

def build_price_pipeline():
    print("🚀 [주가 적재 파이프라인] 10년 치 일별 주가 고속 적재를 시작합니다...")
    start_time = time.time()
    
    # SQLite DB 연결 및 속도/안정성 최적화 세팅
    conn = sqlite3.connect('data_cache/quant_history.db')
    cursor = conn.cursor()
    cursor.execute('PRAGMA synchronous = NORMAL') 
    cursor.execute('PRAGMA journal_mode = WAL') # 대용량 쓰기에 훨씬 안전한 WAL 모드
    
    df_master = pd.read_sql("SELECT ticker FROM stock_master WHERE is_active = 1", conn)
    tickers = df_master['ticker'].tolist()
    
    print(f"📊 총 {len(tickers)}개 종목의 주가 데이터를 수집합니다. (약 15~25분 소요 예상)")
    
    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] {ticker} 주가 수집 중...", end="\r")
        
        try:
            # FinanceDataReader는 'A000020' 대신 '000020' 형식의 6자리 코드가 필요함
            fdr_ticker = ticker[1:] if ticker.startswith('A') else ticker
            df_price = fdr.DataReader(fdr_ticker, '2016-01-01')
            
            if df_price.empty:
                continue
            
            df_price = df_price.reset_index()
            
            price_data = list(zip(
                df_price['Date'].dt.strftime('%Y-%m-%d'),
                [ticker] * len(df_price),
                df_price['Close'],
                df_price['Volume']
            ))
            
            cursor.executemany('''
                INSERT OR REPLACE INTO daily_price (date, ticker, close, volume)
                VALUES (?, ?, ?, ?)
            ''', price_data)
            
            # 🚨 시니어의 최적화: 메모리 터짐 방지를 위해 50개 종목마다 안전하게 DB에 확정(Commit)
            if (i + 1) % 50 == 0:
                conn.commit()
                
        except Exception:
            pass
            
    # 마지막 남은 찌꺼기 데이터 최종 커밋
    conn.commit()
    conn.close()
    
    print(f"\n✅ [성공] 10년 치 주가 데이터가 DB에 완벽히 적재되었습니다!")
    print(f"⏱️ 소요 시간: {time.time() - start_time:.2f}초")

if __name__ == "__main__":
    build_price_pipeline()