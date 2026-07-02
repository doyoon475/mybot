# %%
import yfinance as yf
import pandas as pd
import time

# 1. 10개의 유명 우량 배당주 리스트로 확장
tickers = ['AAPL', 'MSFT', 'JNJ', 'KO', 'PG', 'PEP', 'MCD', 'WMT', 'T', 'VZ']

data_list = []

print("🏦 저축형 봇: 대량 스캔 및 엑셀 자동 저장 가동...\n")

for ticker_str in tickers:
    try:
        print(f"[{ticker_str}] 재무 데이터 긁어오는 중...")
        ticker = yf.Ticker(ticker_str)
        info = ticker.info
        
        # ROE (자기자본이익률)
        roe = info.get('returnOnEquity', 0)
        if roe is None: roe = 0
            
        # 배당수익률
        div_yield = info.get('trailingAnnualDividendYield', 0)
        if div_yield is None or div_yield == 0: 
            div_yield = info.get('dividendYield', 0)
        if div_yield is None: div_yield = 0
            
        data_list.append({
            'Ticker': ticker_str,
            'ROE': roe,
            'Dividend_Yield': div_yield
        })
        
        # 서버 차단 방지를 위해 0.5초씩 휴식
        time.sleep(0.5)
        
    except Exception as e:
        print(f"{ticker_str} 에러 발생: {e}")

# 2. 예쁜 표(데이터프레임)로 변환 및 결측치 방어
df = pd.DataFrame(data_list)
df['ROE'] = df['ROE'].fillna(0)
df['Dividend_Yield'] = df['Dividend_Yield'].fillna(0)

# 퍼센트(%) 단위 변환
df['ROE(%)'] = (df['ROE'] * 100).round(2)
df['Dividend_Yield(%)'] = (df['Dividend_Yield'] * 100).round(2)

# 사용할 알맹이 컬럼만 따로 빼기
final_df = df[['Ticker', 'ROE(%)', 'Dividend_Yield(%)']]

# --- 🎯 핵심 마법 1: 데이터 정렬 ---
# ROE(%)가 높은 순서(내림차순, ascending=False)대로 줄 세우기!
final_df = final_df.sort_values(by='ROE(%)', ascending=False)

# 줄 세운 후 왼쪽 인덱스 번호(0,1,2..)를 1등부터 깔끔하게 새로고침
final_df = final_df.reset_index(drop=True)

# --- 🎯 핵심 마법 2: 엑셀로 자동 추출 ---
excel_filename = "sp500_top_stocks.xlsx"
final_df.to_excel(excel_filename, index=False)

print("\n✅ 데이터 스캔 및 정렬 완료! (ROE 기준 순위)")
print(final_df)
print(f"\n💾 엑셀 파일 자동 저장 완료! 좌측 탐색기에서 [{excel_filename}]를 확인하세요!")
# %%# %%
%pip install openpyxl
import yfinance as yf
import pandas as pd
import time

# ... (아래 봇 코드는 기존과 완벽하게 동일합니다) ...
# %%
