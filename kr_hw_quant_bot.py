import sys, io, urllib.request, json, time, os, zipfile, xml.etree.ElementTree as ET, datetime, math
import subprocess

# 1. 필수 라이브러리 자동 설치 (고장난 lxml 대신 bs4, html5lib 추가)
try:
    import FinanceDataReader as fdr 
    import pandas as pd
    import openpyxl
    import requests
    import bs4
except ImportError:
    print("⚠️ 새 해석기(BeautifulSoup) 설치 중...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "finance-datareader", "pandas", "openpyxl", "requests", "beautifulsoup4", "html5lib"])
    import FinanceDataReader as fdr
    import pandas as pd
    import requests

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
except:
    pass

# 💡 DART API 키
API_KEY = 'ec7e8750b86c77e146f1630f3d42d848b38f0bd1'

def get_price_data(stock_code):
    today = datetime.datetime.today()
    date_1m_ago = today - datetime.timedelta(days=30)
    date_12m_ago = today - datetime.timedelta(days=365)
    
    try:
        df = fdr.DataReader(stock_code, date_12m_ago, today)
        if len(df) < 200: return None
        
        df_recent_20 = df.iloc[-20:]
        avg_trd_val = (df_recent_20['Close'] * df_recent_20['Volume']).mean()
        
        df_past = df.loc[:date_1m_ago]
        if len(df_past) < 10: return None
        
        price_past = df_past['Close'].iloc[0]
        price_recent = df_past['Close'].iloc[-1]
        price_mom = (price_recent - price_past) / price_past
        
        daily_returns = df_past['Close'].pct_change().dropna()
        sharpe = 0 if daily_returns.std() == 0 else (daily_returns.mean() / daily_returns.std()) * math.sqrt(252)
            
        return {
            'price_mom': price_mom,
            'avg_trd_val': avg_trd_val,
            'sharpe_ratio': sharpe
        }
    except:
        return None

print("=== [0단계] K-하드웨어/혁신 필터 가동 (섹터 및 시총 검사) ===", flush=True)
try:
    krx_main = fdr.StockListing('KRX')
    krx_main['Code'] = krx_main['Code'].astype(str).str.zfill(6)
    
    krx_url = 'http://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13'
    res = requests.get(krx_url)
    res.encoding = 'euc-kr'
    
    # 💡 핵심 해결: 억지 부리는 lxml을 무시하고, 강제로 flavor='bs4' 사용 지시!
    krx_kind = pd.read_html(io.StringIO(res.text), header=0, flavor='bs4')[0]
    krx_kind['종목코드'] = krx_kind['종목코드'].astype(str).str.zfill(6)
    
    krx_df = pd.merge(krx_main, krx_kind[['종목코드', '업종']], left_on='Code', right_on='종목코드', how='inner')
    krx_df['업종'] = krx_df['업종'].fillna('')
    
    hw_keywords = '반도체|전자|기계|장비|컴퓨터|통신|전기|부품|디스플레이|로봇|자동화|소프트웨어|IT'
    krx_hw = krx_df[krx_df['업종'].str.contains(hw_keywords, na=False)]
    
    krx_filtered = krx_hw[krx_hw['Marcap'] >= 50000000000]
    valid_codes = set(krx_filtered['Code'].tolist())
    
    print(f"🛡️ 1차 방어 통과: 혁신 하드웨어 섹터 & 시총 500억 이상 종목 {len(valid_codes)}개 확보\n", flush=True)
    
    if len(valid_codes) == 0:
        print("⚠️ [오류] 조건에 맞는 종목이 0개입니다. 프로그램을 즉시 종료합니다.", flush=True)
        sys.exit()
        
except Exception as e:
    print(f"⚠️ 필터링 실패({e}). 프로그램을 종료합니다.", flush=True)
    sys.exit()

print("=== [1단계] 재무, 유동성, 변동성(샤프지수) 정밀 수집 시작 ===", flush=True)

file_path = 'CORPCODE.xml'
if not os.path.exists(file_path):
    url = f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={API_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                z.extractall()
    except: pass

tree = ET.parse(file_path)
corp_list = []
for corp in tree.findall('list'):
    sc = corp.find('stock_code').text
    if sc and sc.strip():
        corp_list.append({
            'name': corp.find('corp_name').text,
            'dart_code': corp.find('corp_code').text,
            'stock_code': sc.strip()
        })

raw_data_list = []
total_corps = len(corp_list)
print(f"총 {total_corps}개 상장사 중 타겟 하드웨어 기업 필터링 검사를 시작합니다.\n", flush=True)

for idx, corp in enumerate(corp_list): 
    name, dart_code, stock_code = corp['name'], corp['dart_code'], corp['stock_code']
    
    if valid_codes and stock_code not in valid_codes:
        continue

    time.sleep(1.0) 
    url = f"https://opendart.fss.or.kr/api/fnlttSinglAcnt.json?crtfc_key={API_KEY}&corp_code={dart_code}&bsns_year=2025&reprt_code=11013"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            status = data.get('status')
            
            if status == '000':
                v = {'ni_cur':0, 'ni_prev':0, 'te':0, 'debt':0, 'cur_ast':0, 'cur_debt':0, 'rev':0, 'cfo':0}
                def parse_amt(amt_str):
                    amt_str = str(amt_str).replace(',', '').strip()
                    if not amt_str or amt_str == '-': return 0
                    try: return int(amt_str)
                    except: return 0

                for fs_type in ['OFS', 'CFS']: 
                    for item in data.get('list', []):
                        if item.get('fs_div') == fs_type:
                            acnt = item.get('account_nm', '').replace(' ', '')
                            amt_cur = parse_amt(item.get('thstrm_amount', '0'))
                            amt_prev = parse_amt(item.get('frmtrm_amount', '0'))
                            if '순이익' in acnt: v['ni_cur'], v['ni_prev'] = amt_cur, amt_prev
                            if '자본총계' in acnt: v['te'] = amt_cur
                            if '부채총계' in acnt: v['debt'] = amt_cur
                            if '유동자산' in acnt: v['cur_ast'] = amt_cur
                            if '유동부채' in acnt: v['cur_debt'] = amt_cur
                            if '매출' in acnt or '수익' in acnt: v['rev'] = amt_cur
                            if '현금' in acnt and '영업' in acnt: v['cfo'] = amt_cur

                if v['te'] > 0 and v['rev'] > 0:
                    roe = v['ni_cur'] / v['te']
                    pcr_inv = v['cfo'] / v['rev'] if v['rev'] != 0 else 0
                    cur_ratio = (v['cur_ast'] / v['cur_debt']) * 100 if v['cur_debt'] > 0 else 0
                    debt_ratio = (v['debt'] / v['te']) * 100 if v['te'] > 0 else 999
                    f_score = (1 if v['ni_cur'] > 0 else 0) + (1 if v['cfo'] > 0 else 0) + (1 if cur_ratio >= 100 else 0) + (1 if debt_ratio <= 200 else 0)
                    earn_mom = (v['ni_cur'] - v['ni_prev']) / abs(v['ni_prev']) if v['ni_prev'] != 0 else 0
                    
                    p_data = get_price_data(stock_code)
                    
                    if p_data:
                        if p_data['avg_trd_val'] < 1000000000:
                            print(f"[{idx+1}/{total_corps}] ⛔ 거래량 스킵: {name} (유동성 부족)", flush=True)
                            continue
                            
                        if p_data['price_mom'] <= 0:
                            print(f"[{idx+1}/{total_corps}] ⛔ 하락 스킵: {name} (수익률 마이너스)", flush=True)
                            continue
                            
                        raw_data_list.append({
                            'name': name, 'roe': roe, 'pcr_inv': pcr_inv, 
                            'cur_ratio': cur_ratio, 'f_score': f_score,
                            'earn_mom': earn_mom, 
                            'price_mom': p_data['price_mom'],
                            'sharpe': p_data['sharpe_ratio'],
                            'avg_trd_val': p_data['avg_trd_val']
                        })
                        print(f"[{idx+1}/{total_corps}] ✅ H/W 통과: {name} (샤프지수: {p_data['sharpe_ratio']:.2f})", flush=True)
                    else:
                        print(f"[{idx+1}/{total_corps}] ⚠️ 주가 에러: {name}", flush=True)
                else:
                    print(f"[{idx+1}/{total_corps}] ⚠️ 재무 부족: {name}", flush=True)
                    
            elif status == '020':
                print(f"\n🚨 API 일일 한도 소진. 모인 데이터로 분석합니다.", flush=True)
                break 
                
    except Exception as e:
        pass

if not raw_data_list:
    print("수집된 데이터가 없습니다. 분석을 종료합니다.", flush=True)
    sys.exit()

print(f"\n=== [2단계] 통계적 전처리 (총 {len(raw_data_list)}개 최정예 종목 랭킹화) ===", flush=True)

def get_percentile_val(vals, p):
    s = sorted(vals)
    idx = int(math.ceil((len(s) * p) - 1))
    return s[max(0, min(idx, len(s)-1))]

roe_vals = [x['roe'] for x in raw_data_list]
emom_vals = [x['earn_mom'] for x in raw_data_list]
sharpe_vals = [x['sharpe'] for x in raw_data_list] 
pcr_vals = [x['pcr_inv'] for x in raw_data_list]

roe_lower, roe_upper = get_percentile_val(roe_vals, 0.01), get_percentile_val(roe_vals, 0.99)
emom_lower, emom_upper = get_percentile_val(emom_vals, 0.01), get_percentile_val(emom_vals, 0.99)
sharpe_lower, sharpe_upper = get_percentile_val(sharpe_vals, 0.01), get_percentile_val(sharpe_vals, 0.99)
pcr_lower, pcr_upper = get_percentile_val(pcr_vals, 0.01), get_percentile_val(pcr_vals, 0.99)

for item in raw_data_list:
    item['roe_win'] = max(roe_lower, min(item['roe'], roe_upper))
    item['emom_win'] = max(emom_lower, min(item['earn_mom'], emom_upper))
    item['sharpe_win'] = max(sharpe_lower, min(item['sharpe'], sharpe_upper))
    item['pcr_win'] = max(pcr_lower, min(item['pcr_inv'], pcr_upper))
    item['cur_ratio_cap'] = min(item['cur_ratio'], 500)

roe_win_vals = [x['roe_win'] for x in raw_data_list]
roe_mean = sum(roe_win_vals) / len(roe_win_vals)
roe_var = sum((x - roe_mean)**2 for x in roe_win_vals) / len(roe_win_vals)
roe_std = math.sqrt(roe_var) if roe_var > 0 else 1

n = len(raw_data_list)
for key, rank_key in [('pcr_win', 'val_rank'), ('emom_win', 'emom_rank'), ('sharpe_win', 'pmom_rank')]:
    raw_data_list.sort(key=lambda x: x[key])
    for i, item in enumerate(raw_data_list):
        item[rank_key] = (i + 1) / n

print("\n=== [3단계] 최종 블렌딩 및 결과 산출 ===", flush=True)

results = []
for item in raw_data_list:
    item['roe_z'] = (item['roe_win'] - roe_mean) / roe_std
    item['roe_score'] = max(0, min((item['roe_z'] / 6) + 0.5, 1))
    
    quality_score = (item['roe_score'] * 0.5) + ((item['f_score'] / 4) * 0.3) + ((item['cur_ratio_cap'] / 500) * 0.2)
    value_score = item['val_rank']
    momentum_score = (item['pmom_rank'] * 0.5) + (item['emom_rank'] * 0.5)
    
    final_score = (value_score * 0.333) + (quality_score * 0.333) + (momentum_score * 0.333)
    
    results.append({
        'name': item['name'], 'score': final_score,
        'val': value_score, 'qual': quality_score, 'mom': momentum_score,
        'sharpe': item['sharpe'], 'trd_val_100m': int(item['avg_trd_val'] / 100000000)
    })

# =========================================================================
# 절대 경로 강제 지정 (무조건 C:\mybot\data_cache 로 저장)
# =========================================================================
save_folder = r"C:\mybot\data_cache"

if not os.path.exists(save_folder): 
    os.makedirs(save_folder)

results_df = pd.DataFrame(results)
results_df.columns = ['종목명', '최종점수', '가치점수', '우량점수', '모멘텀점수', '샤프지수', '거래대금(억)']
results_df = results_df.sort_values(by='최종점수', ascending=False)

filename = os.path.join(save_folder, "7월_최종_퀀트랭킹.xlsx")
results_df.to_excel(filename, index=False)
    
print(f"\n🎉 분석 완료! 엑셀 파일이 도윤님의 전용 금고에 무사히 보관되었습니다!")
print(f"📂 저장 위치: {filename} 🚀", flush=True)