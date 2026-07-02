import sys, subprocess, os, time
from datetime import datetime

# 🛡️ [방어막] 필수 도구 자동 설치 (pykrx 추가)
try:
    import pandas as pd
    import numpy as np
    import OpenDartReader
    import yfinance as yf
    import pykrx
except ImportError:
    print("⚠️ 필수 라이브러리 자동 세팅 중...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "numpy", "requests", "lxml", "beautifulsoup4", "html5lib", "OpenDartReader", "yfinance", "pykrx", "--quiet"])
    import pandas as pd
    import numpy as np
    import OpenDartReader
    import yfinance as yf
    import pykrx

from pykrx import stock

# 💡 DART API 설정
api_key = 'ec7e8750b86c77e146f1630f3d42d848b38f0bd1'
dart = OpenDartReader(api_key)

print("🏛️ [마스터 봇 V2] pykrx와 DART를 결합하여 압도적인 속도로 엔진을 가동합니다...")

# -------------------------------------------------------------
# 1단계: pykrx를 이용해 전 종목 시가총액 일괄 다운로드 (야후 서버 차단 완벽 회피)
# -------------------------------------------------------------
today_date = datetime.today().strftime("%Y%m%d")
print("📊 [1/3] 한국거래소(KRX) 상장사 및 시가총액 데이터 다운로드 중...")

try:
    df_kospi = stock.get_market_cap(today_date, market="KOSPI")
    df_kosdaq = stock.get_market_cap(today_date, market="KOSDAQ")
    
    df_market_cap = pd.concat([df_kospi, df_kosdaq]).reset_index()
    df_market_cap.rename(columns={'티커': '종목코드', '시가총액': 'MarketCap'}, inplace=True)
    
    tickers = stock.get_market_ticker_list(today_date, market="ALL")
    names = [stock.get_market_ticker_name(t) for t in tickers]
    df_names = pd.DataFrame({'종목코드': tickers, 'Name': names})
    
    df_master = pd.merge(df_names, df_market_cap[['종목코드', 'MarketCap']], on='종목코드', how='inner')
    
    kospi_list = df_kospi.index.tolist()
    df_master['Ticker'] = df_master['종목코드'].apply(lambda x: x + '.KS' if x in kospi_list else x + '.KQ')
    
    total_items = len(df_master)
    print(f"✅ 총 {total_items}개 종목 시가총액 데이터 수집 완료!")

except Exception as e:
    print(f"❌ KRX 데이터 수집 실패: {e}")
    sys.exit()

data_list = []

# -------------------------------------------------------------
# 2단계: 최적화된 DART & Yahoo 스캔 루프 (통신량 대폭 감소)
# -------------------------------------------------------------
print(f"🔍 [2/3] 초고속 재무제표 스캔 시작...")

for i, row in df_master.iterrows():
    ticker_str = row['Ticker']
    name = row['Name']
    mkt_cap = row['MarketCap']
    
    print(f"[{i+1}/{total_items}] 🔍 {name} 분석 중...", end=" ")
    
    # 💡 [최적화 1] 시가총액 500억 미만은 DART를 조회하기도 전에 즉시 탈락
    if pd.isna(mkt_cap) or mkt_cap < 50000000000:
        print(f"❌ [탈락] 조건 미달 (시총: {mkt_cap/100000000:,.0f}억)")
        continue
    
    try:
        # [DART] 2025년 결산 사업보고서 조회
        fs = dart.finstate(name, 2025, reprt_code='11011')
        
        if fs is None or len(fs) == 0: 
            print("⏭️ [패스] DART 사업보고서 없음")
            continue
        
        op_data = fs[fs['account_nm'] == '영업이익']
        
        if op_data.empty:
            print("⏭️ [패스] 영업이익 데이터 없음 (금융주 또는 지주사)")
            continue
            
        raw_op = str(op_data['thstrm_amount'].iloc[0]).replace(',', '').strip()
        
        if raw_op == '' or raw_op == '-' or pd.isna(raw_op):
            op_profit = 0.0
        else:
            try:
                op_profit = float(raw_op)
            except ValueError:
                op_profit = 0.0 
        
        # 💡 [최적화 2] 영업이익 적자 탈락
        if op_profit <= 0: 
            print(f"❌ [탈락] 조건 미달 (영업이익: {op_profit/100000000:,.0f}억)")
            continue
        
        # 💡 [최적화 3] 시총 500억 이상 & 흑자 기업에게만 야후 파이낸스 접속
        ticker = yf.Ticker(ticker_str)
        info = ticker.info
        per = info.get('forwardPE', 999)
        rev_growth = info.get('revenueGrowth', 0)

        data_list.append({
            'Name': name,
            'Ticker': ticker_str,
            'OCF': op_profit, 
            'MarketCap': mkt_cap,
            'PER': per,
            'Rev_Growth': rev_growth
        })
        print(f"✅ [통과] 바구니에 담겼습니다! (영업이익: {op_profit/100000000:,.0f}억)")
        
        time.sleep(0.1) 
        
    except Exception as e:
        if "013" not in str(e):
            print(f"⚠️ [에러] {e}") 
        else:
            print("⏭️ [패스] DART 조회 데이터 없음")
        continue

# -------------------------------------------------------------
# 3단계: 결과 저장 (C:\mybot\data_cache 강제 고정)
# -------------------------------------------------------------
print(f"\n✅ 스캔 완료! 필터링을 통과한 알짜 우량주 개수: {len(data_list)}개")

if len(data_list) > 0:
    df = pd.DataFrame(data_list)
    df = df.sort_values(by='OCF', ascending=False)
    
    # 무조건 전용 금고로 직행
    save_dir = r"C:\mybot\data_cache"
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        
    # 매번 날짜가 찍힌 이름으로 새롭게 저장 (덮어쓰기 방지)
    file_name = f"K_Quant_Result_v2_{datetime.now().strftime('%Y%m%d')}.xlsx"
    full_path = os.path.join(save_dir, file_name)
    
    df.to_excel(full_path, index=False)
    
    print(f"💾 데이터 수집 완료! 엑셀 파일이 전용 금고에 무사히 보관되었습니다!")
    print(f"📂 저장 위치: {full_path}")
    print("이제 본체 봇(kr_hw_quant_bot.py)을 실행하세요!")
else:
    print("⚠️ 필터를 통과한 종목이 없습니다.")