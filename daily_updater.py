import os
import sys
import time
from datetime import datetime

# 기존 작성된 모듈들 임포트
from price_etl import build_price_pipeline
from dart_api_manager import fetch_recent_financials

# TODO: 향후 DART 데이터를 파싱하여 monthly_factor에 넣는 로직 추가 예정
def run_daily_dart_update():
    print("📡 [1/2] DART API 기반 최신 공시/재무 데이터 업데이트 시작...")
    # 예시: 시총 상위 종목이나 관심 종목 리스트를 순회하며 업데이트 (현재는 뼈대 연동)
    # fetch_recent_financials('005930')
    time.sleep(2)
    print("✅ DART 데이터 업데이트 완료 (로직 확장 예정)")

def run_daily_price_update():
    print("📈 [2/2] 주가 데이터(FinanceDataReader) 최신화 시작...")
    build_price_pipeline()

def run_daily_pipeline():
    print("==================================================")
    print(f"🤖 [퀀트 자동화 봇] 일일 데이터 파이프라인 가동: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("==================================================")
    
    start_time = time.time()
    
    try:
        run_daily_dart_update()
        print("-" * 50)
        run_daily_price_update()
        print("==================================================")
        print(f"🎉 [성공] 모든 일일 데이터 업데이트가 완료되었습니다! (소요 시간: {time.time() - start_time:.2f}초)")
    except Exception as e:
        print("🚨 [실패] 일일 업데이트 중 치명적 에러 발생:", e)

if __name__ == "__main__":
    run_daily_pipeline()
