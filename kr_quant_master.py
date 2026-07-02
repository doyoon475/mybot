import sys, subprocess, os, time
from io import StringIO

# 🛡️ [방어막] 터미널 경로 강제 고정
try:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
except Exception:
    pass

# 🛡️ [방어막] 필수 도구 자동 설치
try:
    import pandas as pd
    import numpy as np
    import requests
    import bs4
    import OpenDartReader
    import yfinance as yf
except ImportError:
    print("⚠️ 필수 라이브러리 자동 세팅 중...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "numpy", "requests", "lxml", "beautifulsoup4", "html5lib", "OpenDartReader", "yfinance", "--quiet"])
    import pandas as pd
    import numpy as np
    import requests
    import bs4
    import OpenDartReader
    import yfinance as yf

# 💡 DART API 설정
api_key = 'ec7e8750b86c77e146f1630f3d42d848b38f0bd1'
dart = OpenDartReader(api_key)

print("🏛️ DART와 야후 파이낸스를 결합하여 K-하드웨어 퀀트 엔진을 가동합니다...")

# 1. 한국거래소(KRX) 상장사 리스트 수집
krx_url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
try:
    res = requests.get(krx_url)
    res.encoding = 'euc-kr' 
    krx_df = pd.read_html(StringIO(res.text), header=0, flavor='bs4')[0]
except Exception as e:
    print(f"❌ KRX 데이터 수집 실패: {e}")
    sys.exit()

krx_df['종목코드'] = krx_df['종목코드'].astype(str).str.zfill(6)
krx_df['Ticker'] = np.where(krx_df['시장구분'] == 'KOSPI', krx_df['종목코드'] + '.KS', krx_df['종목코드'] + '.KQ')

data_list = []
total_items = len(krx_df)
print(f"📊 총 {total_items}개 종목 스캔을 시작합니다...")

# 2. 전 종목 DART & Yahoo 스캔 루프
for i, row in krx_df.iterrows():
    ticker_str = row['Ticker']
    name = row['회사명']
    
    print(f"[{i+1}/{total_items}] 🔍 {name} 분석 중...", end=" ")
    
    try:
        # [DART] 2025년 결산 사업보고서 조회 (요약본)
        fs = dart.finstate(name, 2025, reprt_code='11011')
        
        if fs is None or len(fs) == 0: 
            print("⏭️ [패스] DART 사업보고서 없음")
            continue
        
        # 💡 [핵심 수정] 없는 현금흐름 대신, 가장 확실한 '영업이익' 계정을 찾도록 변경!
        op_data = fs[fs['account_nm'] == '영업이익']
        
        if op_data.empty:
            print("⏭️ [패스] 영업이익 데이터 없음 (금융주 또는 지주사)")
            continue
            
        # DART 데이터를 무조건 '숫자(float)'로 강제 변환
        raw_op = str(op_data['thstrm_amount'].iloc[0]).replace(',', '').strip()
        
        if raw_op == '' or raw_op == '-' or pd.isna(raw_op):
            op_profit = 0.0
        else:
            try:
                op_profit = float(raw_op)
            except ValueError:
                op_profit = 0.0 
        
        # [Yahoo] 시가총액 등 시장 데이터 수집
        ticker = yf.Ticker(ticker_str)
        info = ticker.info
        
        raw_mkt_cap = info.get('marketCap', 0)
        if raw_mkt_cap is None:
            raw_mkt_cap = 0
            
        try:
            mkt_cap = float(raw_mkt_cap)
        except ValueError:
            mkt_cap = 0.0

        # 💡 [필터링 조건] 영업이익 적자(0 이하) 탈락, 시가총액 500억 미만 탈락
        if op_profit <= 0 or mkt_cap < 50000000000: 
            print(f"❌ [탈락] 조건 미달 (영업이익: {op_profit/100000000:,.0f}억, 시총: {mkt_cap/100000000:,.0f}억)")
            continue
        
        # 생존자들만 리스트에 추가 (기존 코드와의 호환을 위해 OCF라는 이름표에 영업이익을 담습니다)
        data_list.append({
            'Name': name,
            'Ticker': ticker_str,
            'OCF': op_profit, 
            'MarketCap': mkt_cap,
            'PER': info.get('forwardPE', 999),
            'Rev_Growth': info.get('revenueGrowth', 0)
        })
        print(f"✅ [통과] 바구니에 담겼습니다! (영업이익: {op_profit/100000000:,.0f}억)")
        
        time.sleep(0.2) 
        
    except Exception as e:
        if "013" not in str(e):
            print(f"⚠️ [에러] {e}") 
        else:
            print("⏭️ [패스] DART 조회 데이터 없음")
        continue

# 3. 스캔 종료 및 결과 저장
print(f"\n✅ 스캔 완료! 필터링을 통과한 알짜 우량주 개수: {len(data_list)}개")

if len(data_list) > 0:
    df = pd.DataFrame(data_list)
    df = df.sort_values(by='OCF', ascending=False)
    
    excel_file = "K_Quant_Result.xlsx"
    df.to_excel(excel_file, index=False)
    print(f"💾 데이터 수집 완료! '{excel_file}'에 저장되었습니다. 이제 봇(kr_hw_quant_bot.py)을 실행하세요!")
else:
    print("⚠️ 필터를 통과한 종목이 없습니다.")