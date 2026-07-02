import urllib.request
import json

print(">> 글로벌 금융 서버(야후 파이낸스) 다이렉트 접속 중...")

# 삼성전자의 고유 티커(005930.KS)를 사용해 실시간 가격을 요청하는 주소
url = "https://query1.finance.yahoo.com/v8/finance/chart/005930.KS"

# 서버가 봇을 차단하지 못하도록, 사람(크롬 브라우저)이 접속하는 것처럼 위장하는 신분증(User-Agent)
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})

try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        
        # 복잡한 데이터 속에서 '현재가'만 핀셋으로 뽑아내기
        current_price = data['chart']['result'][0]['meta']['regularMarketPrice']
        
        print("\n=== 삼성전자 실시간 주가 데이터 ===")
        print(f"현재 시장 거래가: {current_price:,} 원")
        print("===================================")
        
except Exception as e:
    print("\n[오류] 주가 데이터를 가져오지 못했습니다:", e)