import sys, os, subprocess
from datetime import datetime

# 🛡️ [방어막] 시각화 및 백테스트 필수 도구 자동 설치
try:
    import pandas as pd
    import numpy as np
    import FinanceDataReader as fdr
    import matplotlib.pyplot as plt
except ImportError:
    print("⚠️ 백테스팅 시각화 툴 자동 설치 중...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "numpy", "finance-datareader", "matplotlib", "--quiet"])
    import pandas as pd
    import numpy as np
    import FinanceDataReader as fdr
    import matplotlib.pyplot as plt

# 📊 한글 폰트 깨짐 방지 설정
import platform
if platform.system() == 'Windows':
    plt.rc('font', family='Malgun Gothic')
elif platform.system() == 'Darwin':
    plt.rc('font', family='AppleGothic')
plt.rcParams['axes.unicode_minus'] = False

# =========================================================
# 1. 도윤님 맞춤형 백테스트 룰 설정 (입맛대로 수정하세요!)
# =========================================================
INITIAL_CAP = 10000000    # 초기 자본금 (예: 1천만 원 - 원하시는 금액으로 끝에 0을 빼고 더해보세요!)
MONTHLY_INV = 500000      # 매월 추가 적립금 (50만 원)
TOP_N = 20                # 엑셀에서 가져올 상위 종목 개수 (Top 20)
START_DATE = '2021-07-01' # 백테스트 시작일 (최근 5년)
END_DATE = '2026-07-01'   # 백테스트 종료일

print("🚀 도윤님 맞춤형 백테스팅 엔진 가동 중...\n")

# =========================================================
# 2. 7월 한국장 최종 엑셀 파일에서 1~20위 종목명 불러오기
# =========================================================
file_path = r"data_cache/7월_최종_퀀트랭킹.xlsx"
try:
    df_rank = pd.read_excel(file_path)
    top_names = df_rank.head(TOP_N)['종목명'].tolist()
    print(f"✅ 백테스트 대상 Top {TOP_N} 종목: {top_names}")
except FileNotFoundError:
    print(f"❌ 엑셀 파일을 찾을 수 없습니다! 경로를 확인해주세요: {file_path}")
    sys.exit()

# 종목명 -> 티커(6자리) 자동 변환
krx_list = fdr.StockListing('KRX')
ticker_dict = dict(zip(krx_list['Name'], krx_list['Code']))
tickers = [ticker_dict.get(name) for name in top_names if ticker_dict.get(name)]

# =========================================================
# 3. 과거 주가 데이터 수집
# =========================================================
print(f"📊 {START_DATE} 부터의 주가 데이터를 수집합니다. 잠시만 기다려주세요...")
prices = pd.DataFrame()
for t, name in zip(tickers, top_names):
    if t:
        prices[name] = fdr.DataReader(t, START_DATE, END_DATE)['Close']

# 백테스트 오류 방지: 신규 상장 종목이 섞여 있을 경우, 모든 종목의 주가가 다 존재하는 날짜부터 시작
prices = prices.dropna()
if prices.empty:
    print("❌ 데이터가 부족합니다. START_DATE를 더 최근으로 조정해주세요.")
    sys.exit()

first_date = prices.index[0]
print(f"📅 실질 백테스트 시작일 (신규상장 반영): {first_date.strftime('%Y-%m-%d')}")

# =========================================================
# 4. 백테스팅 코어 로직 (매월 말 50만원 입금 + 리밸런싱)
# =========================================================
# pandas 버전에 따라 'M' 또는 'ME' 사용
try:
    monthly_dates = prices.resample('ME').last().index 
except:
    monthly_dates = prices.resample('M').last().index 

portfolio_value = []
dates = []

current_capital = INITIAL_CAP
weights = np.ones(len(prices.columns)) / len(prices.columns) # 1/N 동일 비중

# 첫날 매수 (초기 자본금으로)
shares = (current_capital * weights) / prices.iloc[0].values

for i, date in enumerate(prices.index):
    # 1. 당일 주가 기준 포트폴리오 평가액 계산
    daily_val = np.sum(shares * prices.iloc[i].values)
    
    # 2. 월말(월급날) 이벤트: 50만원 추가 및 비율 초기화(리밸런싱)
    if date in monthly_dates and date != first_date:
        daily_val += MONTHLY_INV # 50만원 추가 입금
        shares = (daily_val * weights) / prices.iloc[i].values # 목표 비율에 맞게 주식수 전면 재조정
        
    portfolio_value.append(daily_val)
    dates.append(date)

# =========================================================
# 5. 수익률 및 MDD(최대 낙폭) 계산
# =========================================================
df_result = pd.DataFrame({'Total_Value': portfolio_value}, index=dates)

# 누적 수익률
total_invested = INITIAL_CAP + (MONTHLY_INV * len(monthly_dates))
final_value = df_result['Total_Value'].iloc[-1]
total_return = ((final_value / total_invested) - 1) * 100

# MDD (고점 대비 얼마나 떨어졌었나)
df_result['High_Water_Mark'] = df_result['Total_Value'].cummax()
df_result['Drawdown(%)'] = (df_result['Total_Value'] / df_result['High_Water_Mark'] - 1) * 100
mdd = df_result['Drawdown(%)'].min()

# 연평균 수익률 (CAGR)
years = len(df_result) / 252 # 영업일 기준 년수 변환
cagr = ((final_value / total_invested) ** (1 / years) - 1) * 100

print("\n" + "="*50)
print(f"🏆 도윤's K-하드웨어 AQR 백테스트 결과 리포트")
print("="*50)
print(f"기간: {first_date.strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}")
print(f"초기 투자금: {INITIAL_CAP:,.0f} 원")
print(f"매월 적립금: {MONTHLY_INV:,.0f} 원")
print(f"총 누적 원금: {total_invested:,.0f} 원")
print(f"💰 최종 평가금: {final_value:,.0f} 원")
print("-" * 50)
print(f"📈 단순 누적 수익률: {total_return:.2f}%")
print(f"🔥 연평균 수익률(CAGR): {cagr:.2f}%")
print(f"🥶 최대 낙폭(MDD): {mdd:.2f}% (가장 고통스러웠던 순간)")
print("="*50)

# =========================================================
# 6. 아름다운 자산 성장 그래프 그리기
# =========================================================
plt.figure(figsize=(12, 6))
plt.plot(df_result.index, df_result['Total_Value'], label='포트폴리오 평가액', color='firebrick', linewidth=2)
# 내가 넣은 원금 선 (비교용)
invested_line = [INITIAL_CAP + (MONTHLY_INV * i) for i in range(len(df_result))]
# 시각적 오차 방지를 위해 월말마다 원금이 오르는 계단식 선명도 조정은 생략하고 단순 직선형태로 대략 표현
plt.plot(df_result.index, np.linspace(INITIAL_CAP, total_invested, len(df_result)), label='총 투입 원금', color='gray', linestyle='--')

plt.title('도윤 포트폴리오 자산 성장 곡선 (매월 50만원 적립 & 리밸런싱)')
plt.xlabel('Date')
plt.ylabel('Asset Value (KRW)')
plt.legend()
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
