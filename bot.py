import urllib.request
import json

# 외부 부품(pip) 일절 사용 금지! 파이썬 순정 기능만 사용합니다.
print(">> 외부 부품 없이 DART 서버 다이렉트 접속 중...")

api_key = 'ec7e8750b86c77e146f1630f3d42d848b38f0bd1'
corp_code = '00126380'  # 삼성전자 고유번호
year = '2025'
reprt_code = '11011'  # 4분기 사업보고서

# DART API에 직접 요청을 보내는 주소
url = f"https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?crtfc_key={api_key}&corp_code={corp_code}&bsns_year={year}&reprt_code={reprt_code}"

req = urllib.request.Request(url)

try:
    with urllib.request.urlopen(req) as response:
        # 받아온 데이터를 파이썬이 읽을 수 있게 변환
        data = json.loads(response.read().decode('utf-8'))
        
        if data.get('status') == '000':
            list_data = data.get('list', [])
            net_income = None
            total_equity = None
            
            for item in list_data:
                account_name = item.get('account_nm', '')
                fs_div = item.get('fs_div', '') # CFS: 연결재무제표
                
                if '당기순이익' in account_name and fs_div == 'CFS':
                    net_income = int(item.get('thstrm_amount', '0').replace(',', ''))
                
                if '자본총계' in account_name and fs_div == 'CFS':
                    total_equity = int(item.get('thstrm_amount', '0').replace(',', ''))
                    
            if net_income and total_equity:
                roe = (net_income / total_equity) * 100
                print("\n=== 삼성전자 2025년 결산 재무 데이터 ===")
                print(f"자본총계: {total_equity:,} 원")
                print(f"당기순이익: {net_income:,} 원")
                print(f"계산된 ROE: {roe:.2f}%")
                print("=========================================")
                print("🎉 축하합니다! 윈도우 환경 지옥을 맨손으로 박살 내셨습니다!")
            else:
                print("DART에서 데이터를 찾았지만, 당기순이익이나 자본총계 항목이 없습니다.")
        else:
            print("DART 서버 응답 에러:", data.get('message'))

except Exception as e:
    print("\n[네트워크 오류] 인터넷이 끊겼거나 DART 서버가 점검 중입니다:", e)