import urllib.request, json, time, os, zipfile, io, xml.etree.ElementTree as ET, datetime

API_KEY = 'ec7e8750b86c77e146f1630f3d42d848b38f0bd1'

# 1. 재무 데이터 추출 (기존 대비 항목 대폭 확장)
def get_dart_data(corp_code):
    url = f"https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?crtfc_key={API_KEY}&corp_code={corp_code}&bsns_year=2025&reprt_code=11011"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('status') == '000':
                # 필요한 항목들 초기화
                vals = {'ni':0, 'te':0, 'debt':0, 'cur_ast':0, 'cur_debt':0}
                for item in data.get('list', []):
                    acnt = item.get('account_nm', '')
                    amt = int(item.get('thstrm_amount', '0').replace(',', ''))
                    if '당기순이익' in acnt and item.get('fs_div') == 'CFS': vals['ni'] = amt
                    if '자본총계' in acnt and item.get('fs_div') == 'CFS': vals['te'] = amt
                    if '부채총계' in acnt and item.get('fs_div') == 'CFS': vals['debt'] = amt
                    if '유동자산' in acnt and item.get('fs_div') == 'CFS': vals['cur_ast'] = amt
                    if '유동부채' in acnt and item.get('fs_div') == 'CFS': vals['cur_debt'] = amt
                return vals
    except: return None
    return None

# 2. 메인 로직
corp_map = get_kospi_corp_map() # 위에서 만든 리스트 함수 사용
results = []

for name, code in corp_map.items():
    time.sleep(0.5) 
    data = get_dart_data(code)
    if data and data['te'] > 0 and data['cur_debt'] > 0:
        roe = (data['ni'] / data['te']) * 100
        debt_ratio = (data['debt'] / data['te']) * 100
        cur_ratio = (data['cur_ast'] / data['cur_debt']) * 100
        
        # [필터링] 부채비율 200% 이하, 유동비율 100% 이상인 종목만 통과
        if debt_ratio <= 200 and cur_ratio >= 100:
            score = roe * 0.5 + cur_ratio * 0.1 # 퀀트 점수 산정
            results.append({'name': name, 'roe': roe, 'score': score})
            print(f"분석 완료: {name} (안정성 통과)")