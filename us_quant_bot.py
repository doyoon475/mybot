import sys, os, time
from datetime import datetime
import pandas as pd
import numpy as np

# [방어막] 필수 라이브러리 세팅
try:
    import yfinance as yf
except ImportError:
    import subprocess
    print("⚠️ yfinance 자동 설치 중...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "--quiet"])
    import yfinance as yf

# 1. 마스터가 캐온 티커 리스트 소환
try:
    df_univ = pd.read_csv("US_Tickers_Universe.csv")
    tickers = df_univ['Ticker'].dropna().tolist()
    print(f"📊 총 {len(tickers)}개의 미국 대장주 스캔을 시작합니다!")
except FileNotFoundError:
    print("❌ 'US_Tickers_Universe.csv' 파일이 없습니다. us_quant_master.py를 먼저 실행하세요!")
    sys.exit()

data_list = []
print("🚀 미국장 전용 AQR Pro 엔진 가동 중... (약 3~5분 소요)\n")

for i, ticker_str in enumerate(tickers):
    print(f"[{i+1}/{len(tickers)}] 🔍 {ticker_str} 스캔 중...", end=" ")
    
    try:
        ticker = yf.Ticker(ticker_str)
        info = ticker.info
        
        # 시총 1조원($1B) 이하 스킵
        mkt_cap = info.get('marketCap', 0)
        if not mkt_cap or mkt_cap < 1000000000: 
            print("⏭️ 시총 미달 패스")
            continue
            
        # 🏢 섹터 정보 (섹터 중립화를 위한 필수 데이터)
        sector = info.get('sector', 'Unknown')
        
        # 💵 재무 데이터 추출
        per = info.get('forwardPE', 999) 
        evebitda = info.get('enterpriseToEbitda', 999)
        roe = info.get('returnOnEquity', -999)
        debt_to_eq = info.get('debtToEquity', 999)
        
        # 🔥 특수 무기 1 & 2: 잉여현금흐름(FCF)과 주주환원(배당)
        fcf = info.get('freeCashflow', 0)
        div_yield = info.get('dividendYield', 0)
        if div_yield is None: div_yield = 0
        
        # FCF Yield (시총 대비 잉여현금흐름 비율 - 높을수록 좋음)
        fcf_yield = fcf / mkt_cap if mkt_cap > 0 else -999
        
        # Shareholder Yield (주주환원율 = 배당수익률 + FCF Yield(자사주매입 여력))
        shareholder_yield = div_yield + (fcf_yield if fcf_yield > 0 else 0)
        
        # 📈 특수 무기 3: 리스크 조정 모멘텀 (변동성(Beta) 대비 수익률)
        mom_12m = info.get('52WeekChange', -999)
        beta = info.get('beta', 1)
        if beta is None or beta <= 0: beta = 1 # Beta가 없거나 음수면 기본값 처리
        
        # 수익이 났을 때는 Beta(변동성)가 낮을수록 점수 상승, 손실일 때는 그대로 반영
        risk_adj_mom = (mom_12m / beta) if mom_12m > 0 else mom_12m
        
        # 필수 데이터 누락 시 패스
        if roe == -999 or mom_12m == -999:
            print("⏭️ 핵심 재무 데이터 누락")
            continue
            
        data_list.append({
            'Ticker': ticker_str,
            'Name': info.get('shortName', ticker_str),
            'Sector': sector,
            'PER': per if per is not None else 999,
            'EV_EBITDA': evebitda if evebitda is not None else 999,
            'FCF_Yield': fcf_yield,
            'ROE': roe if roe is not None else -999,
            'Debt_Ratio': debt_to_eq if debt_to_eq is not None else 999,
            'Shareholder_Yield': shareholder_yield,
            'Risk_Adj_Mom': risk_adj_mom,
            'Mom_12M': mom_12m # 참고용 원본 모멘텀
        })
        print("✅ 장부 기록 완료!")
        time.sleep(0.1) # 야후 차단 방지
        
    except Exception as e:
        print(f"⚠️ 에러 패스: {e}")

# =========================================================
# ⚖️ 특수 무기 4: 섹터 중립화 (Sector Neutrality) 랭킹 시스템
# =========================================================
df = pd.DataFrame(data_list)

# 각 팩터별 점수를 0~1 사이의 백분위(Percentile)로 변환
# 주의: PER, EV_EBITDA, 부채비율은 '낮을수록' 좋으므로 오름차순(True)
# FCF Yield, ROE, 주주환원율, 모멘텀은 '높을수록' 좋으므로 내림차순(False)

# 1. 가치 (Value)
df['Val_Score'] = (
    df.groupby('Sector')['PER'].rank(ascending=True, pct=True) +
    df.groupby('Sector')['EV_EBITDA'].rank(ascending=True, pct=True) +
    df.groupby('Sector')['FCF_Yield'].rank(ascending=False, pct=True)
) / 3

# 2. 우량 (Quality)
df['Qual_Score'] = (
    df.groupby('Sector')['ROE'].rank(ascending=False, pct=True) +
    df.groupby('Sector')['Debt_Ratio'].rank(ascending=True, pct=True) +
    df.groupby('Sector')['Shareholder_Yield'].rank(ascending=False, pct=True)
) / 3

# 3. 모멘텀 (Momentum)
df['Mom_Score'] = df.groupby('Sector')['Risk_Adj_Mom'].rank(ascending=False, pct=True)

# 4. 최종 랭킹: 백분위 점수의 합이 가장 낮은(1등에 가까운) 순서대로 정렬
df['Total_Rank_Score'] = df['Val_Score'] + df['Qual_Score'] + df['Mom_Score']
df = df.sort_values(by='Total_Rank_Score', ascending=True).reset_index(drop=True)
df['Final_Rank'] = df.index + 1

# 가독성을 위해 퍼센트(%) 데이터 포맷팅
df['FCF_Yield(%)'] = (df['FCF_Yield'] * 100).round(2)
df['Shareholder_Yield(%)'] = (df['Shareholder_Yield'] * 100).round(2)
df['Risk_Adj_Mom(%)'] = (df['Risk_Adj_Mom'] * 100).round(2)
df['ROE(%)'] = (df['ROE'] * 100).round(2)

# 최종 출력할 컬럼 정리
final_columns = [
    'Final_Rank', 'Ticker', 'Name', 'Sector', 
    'PER', 'FCF_Yield(%)', 'ROE(%)', 'Shareholder_Yield(%)', 'Risk_Adj_Mom(%)'
]
final_df = df[final_columns]

# =========================================================
# 🔒 무조건 전용 금고에 강제 저장 (숨바꼭질 완벽 차단)
# =========================================================
save_folder = r"data_cache"

if not os.path.exists(save_folder): 
    os.makedirs(save_folder)

filename = os.path.join(save_folder, f"US_AQR_Pro_Edition_{datetime.now().strftime('%Y%m%d')}.xlsx")
final_df.to_excel(filename, index=False)
    
print(f"\n🎉 미국장 스캔 완료! 월스트리트를 씹어먹을 강력한 랭킹이 완성되었습니다!")
print(f"📂 저장 위치: {filename} 🚀", flush=True)