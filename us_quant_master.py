# %%
import yfinance as yf
import pandas as pd
import numpy as np
import time
import urllib.request
import io

print("🌐 S&P 500 및 나스닥 100 종목 수집 중... (스마트 스캔)")

hdr = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

sp_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
req1 = urllib.request.Request(sp_url, headers=hdr)
html1 = urllib.request.urlopen(req1).read().decode('utf-8')
sp_table = pd.read_html(io.StringIO(html1), match='Symbol', flavor='bs4')[0]
sp_tickers = sp_table['Symbol'].tolist()

ndx_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
req2 = urllib.request.Request(ndx_url, headers=hdr)
html2 = urllib.request.urlopen(req2).read().decode('utf-8')
ndx_table = pd.read_html(io.StringIO(html2), match='Ticker', flavor='bs4')[0]
ndx_tickers = ndx_table['Ticker'].tolist()

raw_tickers = list(set(sp_tickers + ndx_tickers))
tickers = [t.replace('.', '-') for t in raw_tickers]
print(f"✅ 총 {len(tickers)}개 유니크 종목 장전 완료!\n")

data_list = []
print("🌌 V5.0 퀀타멘탈 봇: R&D 혁신 및 우주/AI 테마 스캔 시작!\n")

for i, ticker_str in enumerate(tickers, 1):
    print(f"[{i:03d}/{len(tickers)}] 🔍 {ticker_str: <5} 심층 데이터 분석 중...")
    
    try:
        ticker = yf.Ticker(ticker_str)
        info = ticker.info
        
        # --- 🛡️ 방어벽: 거래대금 ---
        avg_volume = info.get('averageVolume', 0)
        current_price = info.get('currentPrice', 0)
        if current_price == 0 or current_price is None:
            current_price = info.get('regularMarketPrice', 0)
            
        dollar_volume = avg_volume * current_price
        if dollar_volume < 10000000:
            print(f"    ㄴ ❌ {ticker_str}: 거래대금 미달")
            continue
            
        # --- 🏭 섹터/산업 테마 보너스 확인 ---
        sector = info.get('sector', 'Unknown')
        industry = info.get('industry', 'Unknown')
        theme_bonus = 0
        # 우주항공, 반도체, 소프트웨어 등 혁신 산업이면 보너스 점수 부여 (낮을수록 좋은 점수 체계이므로 마이너스 처리)
        if type(industry) == str and ('Aerospace' in industry or 'Semiconductor' in industry or 'Software' in industry):
            theme_bonus = -50 
            print(f"    ㄴ 🚀 {ticker_str}: 혁신 테마 포착! ({industry})")
            
        # --- 1. 가치 (Value) + 혁신(PSR) ---
        per = info.get('forwardPE', 9999) or 9999
        pbr = info.get('priceToBook', 9999) or 9999
        psr = info.get('priceToSalesTrailing12Months', 9999) or 9999
        if per <= 0: per = 9999
        if pbr <= 0: pbr = 9999
        if psr <= 0: psr = 9999
            
        # --- 2. 우량 (Quality) + 💡 혁신 마진(Gross Margin) ---
        roe = info.get('returnOnEquity', -999) or -999
        op_margin = info.get('operatingMargins', -999) or -999
        gross_margin = info.get('grossMargins', -999) or -999 # 🆕 R&D 잠재력 지표!
        debt = info.get('debtToEquity', 9999) or 9999
            
        # --- 3. 모멘텀 & 성장 (Growth) ---
        high_52w = info.get('fiftyTwoWeekHigh', 0)
        prox_52w = (current_price / high_52w) if (high_52w and high_52w > 0) else 0
        rev_growth = info.get('revenueGrowth', -999) or -999
        
        hist = ticker.history(period="6mo")
        if hist.empty or len(hist) < 100:
            continue
            
        daily_returns = hist['Close'].pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252)
        
        start_price = hist['Close'].iloc[0]
        end_price = hist['Close'].iloc[-1]
        return_6m = (end_price - start_price) / start_price
        sharpe_momentum = return_6m / volatility if volatility > 0 else 0
        
        data_list.append({
            'Ticker': ticker_str,
            'Industry': industry,
            'PER': per, 'PBR': pbr, 'PSR': psr,
            'ROE': roe, 'Op_Margin': op_margin, 'Gross_Margin': gross_margin, 'Debt': debt,
            'Sharpe': sharpe_momentum, 'High52w_Ratio': prox_52w, 'Rev_Growth': rev_growth,
            'Theme_Bonus': theme_bonus
        })
        
        time.sleep(0.1)
        
    except Exception as e:
        pass

df = pd.DataFrame(data_list)
print("\n⚙️ 스캔 완료! 퀀타멘탈 비율로 최종 점수를 계산합니다...")

# --- 🎯 팩터 순위 계산 ---
df['Rank_Value'] = df['PER'].rank(ascending=True) + df['PBR'].rank(ascending=True) + df['PSR'].rank(ascending=True)

# 💡 우량 점수에 Gross_Margin(매출총이익률) 추가! (높을수록 좋음)
df['Rank_Quality'] = df['ROE'].rank(ascending=False) + df['Op_Margin'].rank(ascending=False) + df['Gross_Margin'].rank(ascending=False) + df['Debt'].rank(ascending=True)

df['Rank_Momentum'] = df['Sharpe'].rank(ascending=False) + df['High52w_Ratio'].rank(ascending=False) + df['Rev_Growth'].rank(ascending=False)

# --- ⚖️ 테마 보너스 적용 ---
# 점수가 낮을수록 1등이므로, Theme_Bonus(-50점)를 더해주면 순위가 수직 상승합니다!
df['Total_Score'] = df['Rank_Value'] + df['Rank_Quality'] + df['Rank_Momentum'] + df['Theme_Bonus']

df = df.sort_values(by='Total_Score', ascending=True).reset_index(drop=True)

# 엑셀 정리
df['Rev_Growth(%)'] = (df['Rev_Growth'] * 100).round(2)
df['Gross_Margin(%)'] = (df['Gross_Margin'] * 100).round(2)
df['PSR'] = df['PSR'].round(2)
df['Sharpe'] = df['Sharpe'].round(2)

final_columns = [
    'Ticker', 'Industry', 'Total_Score',
    'Rank_Momentum', 'Sharpe', 'Rev_Growth(%)',
    'Rank_Quality', 'Gross_Margin(%)', 
    'Rank_Value', 'PSR'
]
final_df = df[final_columns]

excel_filename = "US_Quantamental_V5.xlsx"
final_df.to_excel(excel_filename, index=False)

print(f"\n✅ V5.0 완성! 스토리와 숫자를 모두 잡은 1위 종목은 [{final_df.iloc[0]['Ticker']}] 입니다!")
print(f"좌측 탐색기에서 [{excel_filename}]을 확인해 보세요!")
# %%