import sqlite3
import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import matplotlib.pyplot as plt
import platform
import os

# 📊 한글 폰트 설정
if platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# =========================================================
# 1. ⏱️ 테스트 기간 및 자본금 설정 (원하는 대로 조절하세요!)
# =========================================================
INITIAL_CAP = 10000000    # 초기 자본금 (1천만원)
MONTHLY_INV = 500000      # 매월 적립금 (50만원)
START_DATE = '2021-01-01' # 👈 테스트 시작일
END_DATE = '2026-07-01'   # 👈 테스트 종료일

db_path = r"C:\mybot\data_cache\quant_history.db"

if not os.path.exists(db_path):
    print("❌ 데이터베이스 파일을 찾을 수 없습니다. 경로를 확인해주세요.")
    exit()

# =========================================================
# 2. 🏛️ DB에서 오늘 만든 한국형 HW 봇 종목 리스트 추출
# =========================================================
conn = sqlite3.connect(db_path)
df_db = pd.read_sql("SELECT * FROM kr_quant_ranking", conn)
conn.close()

# 가장 최신 날짜의 랭킹 데이터 가져오기
latest_date = df_db['Date'].max()
df_universe = df_db[df_db['Date'] == latest_date]

print("📌 현재 DB 컬럼 목록:", df_universe.columns.tolist())

# '종목명' 컬럼만 있으므로, 한국거래소(KRX) 데이터와 대조해 코드를 자동 변환합니다.
if '종목명' not in df_universe.columns:
    print("❌ DB에서 '종목명' 컬럼을 찾을 수 없습니다.")
    exit()

print("🔄 종목명 -> 6자리 종목코드로 자동 변환 중...")
# KRX 전체 종목 리스트 가져오기 (이름-코드 짝맞추기용 딕셔너리 생성)
krx_list = fdr.StockListing('KRX')
name_to_code = dict(zip(krx_list['Name'], krx_list['Code']))

univ = {}
for name in df_universe['종목명']:
    code = name_to_code.get(name)
    if code: # 코드를 찾았으면 유니버스에 추가
        univ[code] = name
    else:
        print(f"⚠️ '{name}'의 코드를 찾지 못했습니다. (이름 변경/상폐 가능성)")

tickers = list(univ.keys())

print(f"🎯 변환 완료! 총 {len(tickers)}개의 종목을 유니버스로 가져왔습니다.")
if len(tickers) > 0:
    print(f"🔍 상위 주요 포함 기업: {[univ[t] for t in tickers[:5]]}\n")
else:
    print("❌ 변환된 종목이 없습니다. 백테스트를 종료합니다.")
    exit()

# =========================================================
# 3. 🚀 과거 주가 데이터 수집
# =========================================================
print("📈 과거 주가 데이터 수집 중... (종목 수가 많아 약 30초~1분 소요됩니다)")
prices = pd.DataFrame()
valid_tickers = []

for ticker in tickers:
    try:
        # 데이터 수집 시 모멘텀 계산을 위해 시작일보다 1년 전부터 여유 있게 수집
        df = fdr.DataReader(ticker, '2020-01-01', END_DATE)['Close']
        if not df.empty:
            prices[ticker] = df
            valid_tickers.append(ticker)
    except:
        continue # 상장 폐지나 과거 데이터가 없는 신규주는 제외

prices = prices.sort_index().ffill().bfill()

# 실질 테스트 기간 필터링
test_prices = prices.loc[START_DATE:END_DATE]
monthly_dates = test_prices.resample('ME').last().index

# =========================================================
# 4. 🧠 실전 다이내믹 매매 엔진 가동
# =========================================================
cash = INITIAL_CAP
portfolio = {ticker: 0 for ticker in valid_tickers}
history_dates = []
history_values = []

print("🔥 설정하신 깐깐한 퀀트 룰 적용 시뮬레이션 시작!\n")

for i, today in enumerate(test_prices.index):
    today_prices = test_prices.iloc[i]
    
    # 1. 현재 자산 가치 계산
    stock_value = sum(portfolio[t] * today_prices[t] for t in valid_tickers)
    total_val = cash + stock_value
    
    history_dates.append(today)
    history_values.append(total_val)
    
    # 2. 📅 매월 말일 리밸런싱 진행
    if today in monthly_dates and today != test_prices.index[0]:
        cash += MONTHLY_INV
        total_val += MONTHLY_INV
        
        # 6개월 전 주가와 비교하여 현재 생존 종목 내에서 상대 순위 산출
        past_6m_date = today - pd.DateOffset(months=6)
        past_prices = prices.asof(past_6m_date)
        
        momentum = (today_prices - past_prices) / past_prices
        ranks = momentum.rank(ascending=False)
        
        top10 = ranks[ranks <= 10].index.tolist()
        mid10 = ranks[(ranks >= 11) & (ranks <= 20)].index.tolist()
        losers = ranks[ranks > 20].index.tolist()
        
        # 🗑️ [룰 1] 20위 밖 종목은 무조건 전량 매도
        for t in losers:
            if portfolio[t] > 0:
                cash += portfolio[t] * today_prices[t]
                portfolio[t] = 0
                
        # ⚖️ [룰 2] 11~20위는 유지하되, 비중이 15%를 넘으면 15%선으로 맞춰 부분 매도 (Cap)
        for t in mid10:
            if portfolio[t] > 0:
                current_weight = (portfolio[t] * today_prices[t]) / total_val
                if current_weight > 0.15:
                    excess_value = (current_weight - 0.15) * total_val
                    shares_to_sell = int(excess_value / today_prices[t])
                    portfolio[t] -= shares_to_sell
                    cash += shares_to_sell * today_prices[t]
                    
        # 🎯 [룰 3] 1~10위 종목 매수 (목표 비중 10% 유지)
        for t in top10:
            current_weight = (portfolio[t] * today_prices[t]) / total_val
            target_weight = 0.10
            
            if current_weight < target_weight:
                shortfall_value = (target_weight - current_weight) * total_val
                buy_value = min(shortfall_value, cash) 
                if buy_value > 0 and today_prices[t] > 0:
                    shares_to_buy = int(buy_value / today_prices[t])
                    portfolio[t] += shares_to_buy
                    cash -= shares_to_buy * today_prices[t]

# =========================================================
# 5. 최종 성적표 작성 및 그래프 그리기
# =========================================================
df_result = pd.DataFrame({'Total_Value': history_values}, index=history_dates)
total_invested = INITIAL_CAP + (MONTHLY_INV * len(monthly_dates))
final_value = df_result['Total_Value'].iloc[-1]
total_return = ((final_value / total_invested) - 1) * 100

df_result['High_Water_Mark'] = df_result['Total_Value'].cummax()
df_result['Drawdown'] = (df_result['Total_Value'] / df_result['High_Water_Mark'] - 1) * 100
mdd = df_result['Drawdown'].min()

years = len(df_result) / 252 
cagr = ((final_value / total_invested) ** (1 / years) - 1) * 100

print("="*50)
print(f"🏆 한국형 HW 봇 유니버스 백테스트 성적표")
print("="*50)
print(f"기간: {START_DATE} ~ {END_DATE}")
print(f"총 투입 원금: {total_invested:,.0f} 원")
print(f"💰 최종 평가금: {final_value:,.0f} 원")
print("-" * 50)
print(f"📈 단순 누적 수익률: {total_return:.2f}%")
print(f"🔥 연평균 수익률(CAGR): {cagr:.2f}%")
print(f"🥶 최대 낙폭(MDD): {mdd:.2f}%")
print("="*50)

plt.figure(figsize=(12, 6))
plt.plot(df_result.index, df_result['Total_Value'], label='한국형 HW 포트폴리오', color='crimson')
plt.plot(df_result.index, np.linspace(INITIAL_CAP, total_invested, len(df_result)), label='투입 원금', color='gray', linestyle='--')
plt.title('한국형 HW 봇 DB 기반 다이내믹 백테스트 성과')
plt.xlabel('Date')
plt.ylabel('Asset Value (KRW)')
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()