import pandas as pd
import numpy as np
import FinanceDataReader as fdr
import matplotlib.pyplot as plt
import platform

# 📊 한글 폰트 설정
if platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# =========================================================
# 1. ⏱️ 테스트 기간 및 룰 설정 (여기서 날짜를 조절하세요!)
# =========================================================
INITIAL_CAP = 10000000    # 초기 자본금 (1천만원)
MONTHLY_INV = 500000      # 매월 적립금 (50만원)
START_DATE = '2021-01-01' # 👈 테스트 시작일 
END_DATE = '2026-07-01'   # 👈 테스트 종료일 

# 💡 하드웨어/IT 중심의 30개 유니버스 (우량주 30개 고정)
univ = {
    '005930': '삼성전자', '000660': 'SK하이닉스', '028150': 'GS리테일', '253450': '스튜디오드래곤',
    '066570': 'LG전자', '006400': '삼성SDI', '009150': '삼성전기', '011070': 'LG이노텍',
    '018260': '삼성SDS', '035420': 'NAVER', '035720': '카카오', '036570': '엔씨소프트',
    '005380': '현대차', '012330': '현대모비스', '000270': '기아', '028260': '삼성물산',
    '068270': '셀트리온', '207940': '삼성바이오로직스', '051910': 'LG화학', '096770': 'SK이노베이션',
    '010130': '고려아연', '034020': '두산에너빌리티', '032830': '삼성생명', '316140': '우리금융지주',
    '105560': 'KB금융', '055550': '신한지주', '032640': 'LG유플러스', '017670': 'SK텔레콤',
    '030200': 'KT', '033780': 'KT&G'
}
tickers = list(univ.keys())

print("🚀 과거 주가 데이터 수집 중... (약 10~20초 소요)")
prices = pd.DataFrame()
for ticker in tickers:
    df = fdr.DataReader(ticker, '2020-01-01', END_DATE)['Close']
    prices[ticker] = df

# 🛠️ [핵심 수정 1] 시간표(Index)를 깔끔하게 과거->현재 순으로 강제 정렬하고 최신 문법(ffill) 적용
prices = prices.sort_index()
prices = prices.ffill().dropna()

# 실질 테스트 기간 필터링
test_prices = prices.loc[START_DATE:END_DATE]
monthly_dates = test_prices.resample('ME').last().index

# =========================================================
# 2. 🧠 리얼타임 시뮬레이션 엔진 가동
# =========================================================
cash = INITIAL_CAP
portfolio = {ticker: 0 for ticker in tickers} # 보유 주식 수
history_dates = []
history_values = []

print("🔥 다이내믹 룰(1~10위 매수 / 11~20위 홀딩 / 상한 15%) 적용 백테스팅 시작!\n")

for i, today in enumerate(test_prices.index):
    today_prices = test_prices.iloc[i]
    
    # 1. 현재 포트폴리오 총 가치 계산
    stock_value = sum(portfolio[t] * today_prices[t] for t in tickers)
    total_val = cash + stock_value
    
    history_dates.append(today)
    history_values.append(total_val)
    
    # 2. 📅 월말 리밸런싱 이벤트 발생!
    if today in monthly_dates and today != test_prices.index[0]:
        cash += MONTHLY_INV # 월급 투입!
        total_val += MONTHLY_INV
        
        # [순위 계산] 과거 6개월 전 날짜 산출
        past_6m_date = today - pd.DateOffset(months=6)
        
        # 🛠️ [핵심 수정 2] 에러가 났던 검색 로직을 가장 안전한 asof() 함수로 교체
        # asof()는 지정한 날짜와 가장 가까운 과거의 주가 데이터를 완벽하게 찾아줍니다.
        past_prices = prices.asof(past_6m_date)
            
        momentum = (today_prices - past_prices) / past_prices
        
        # 모멘텀 순위 매기기 (내림차순, 1등이 가장 높은 수익률)
        ranks = momentum.rank(ascending=False)
        
        top10 = ranks[ranks <= 10].index.tolist()
        mid10 = ranks[(ranks >= 11) & (ranks <= 20)].index.tolist()
        losers = ranks[ranks > 20].index.tolist()
        
        # 🗑️ 룰 1: 20위 밖 종목은 가차없이 전량 매도
        for t in losers:
            if portfolio[t] > 0:
                cash += portfolio[t] * today_prices[t]
                portfolio[t] = 0
                
        # ⚖️ 룰 2: 11~20위 홀딩, 단 비중이 15%를 넘으면 15%로 깎아냄 (Cap)
        for t in mid10:
            if portfolio[t] > 0:
                current_weight = (portfolio[t] * today_prices[t]) / total_val
                if current_weight > 0.15:
                    excess_value = (current_weight - 0.15) * total_val
                    shares_to_sell = int(excess_value / today_prices[t])
                    portfolio[t] -= shares_to_sell
                    cash += shares_to_sell * today_prices[t]
                    
        # 🎯 룰 3: 1~10위 종목 매수 (목표 비중 10% 유지)
        for t in top10:
            current_weight = (portfolio[t] * today_prices[t]) / total_val
            target_weight = 0.10
            
            # 비중이 10% 미만일 때만 현금 한도 내에서 추가 매수
            if current_weight < target_weight:
                shortfall_value = (target_weight - current_weight) * total_val
                buy_value = min(shortfall_value, cash) 
                shares_to_buy = int(buy_value / today_prices[t])
                
                portfolio[t] += shares_to_buy
                cash -= shares_to_buy * today_prices[t]

# =========================================================
# 3. 성적표 출력 및 시각화
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
print(f"🏆 하드코어 다이내믹 백테스트 완료")
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
plt.plot(df_result.index, df_result['Total_Value'], label='포트폴리오 평가액', color='darkblue')
plt.plot(df_result.index, np.linspace(INITIAL_CAP, total_invested, len(df_result)), label='투입 원금', color='gray', linestyle='--')
plt.title('다이내믹 백테스트 (1~10 매수, 상한 15% 룰 적용)')
plt.xlabel('Date')
plt.ylabel('Asset Value (KRW)')
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()