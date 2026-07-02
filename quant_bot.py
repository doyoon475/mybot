import sys, io, urllib.request, json, time, os, zipfile, xml.etree.ElementTree as ET, datetime, math
import subprocess

# 필수 라이브러리 확인
try:
    import FinanceDataReader as fdr 
    import pandas as pd
except ImportError:
    print("⚠️ 필수 라이브러리 설치 중...", flush=True)
    subprocess.check_call([sys.executable, "-m", "pip", "install", "finance-datareader", "pandas"])
    import FinanceDataReader as fdr
    import pandas as pd

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')
except:
    pass

# ★ 여기에 본인의 DART API 키를 넣으세요!
API_KEY = 'ec7e8750b86c77e146f1630f3d42d848b38f0bd1'

def get_price_data(stock_code):
    today = datetime.datetime.today()
    date_1m_ago = today - datetime.timedelta(days=30)
    date_12m_ago = today - datetime.timedelta(days=365)
    
    try:
        # 최근 1년 치 주가 데이터 모두 가져오기
        df = fdr.DataReader(stock_code, date_12m_ago, today)
        if len(df) < 200: return None
        
        # 🛡️ 거래대금 계산 (최근 20일 평균, 종가 * 거래량)
        df_recent_20 = df.iloc[-20:]
        avg_trd_val = (df_recent_20['Close'] * df_recent_20['Volume']).mean()
        
        # 최근 1달 전까지의 데이터로 모멘텀 및 샤프지수 계산 (단기 반전 방어)
        df_past = df.loc[:date_1m_ago]
        if len(df_past) < 10: return None
        
        price_past = df_past['Close'].iloc[0]
        price_recent = df_past['Close'].iloc[-1]
        price_mom = (price_recent - price_past) / price_past
        
        # 🛡️ 샤프 지수 계산 (일간 수익률의 평균 / 표준편차 * 연율화)
        daily_returns = df_past['Close'].pct_change().dropna()
        if daily_returns.std() == 0:
            sharpe = 0
        else:
            sharpe = (daily_returns.mean() / daily_returns.std()) * math.sqrt(252)
            
        return {
            'price_mom': price_mom,
            'avg_trd_val': avg_trd_val,
            'sharpe_ratio': sharpe
        }
    except:
        return None

print("=== [0단계] 하드 필터 가동 (한국거래소 시가총액 검사) ===", flush=True)
try:
    krx_df = fdr.StockListing('KRX')
    # 시가총액 1000억 이상만 추출
    krx_filtered = krx_df[krx_df['Marcap'] >= 100000000000]
    valid_codes = set(krx_filtered['Code'].astype(str).str.zfill(6))
    print(f"🛡️ 1차 방어 통과: 시가총액 1,000억 이상 종목 {len(valid_codes)}개 확보\n", flush=True)
except Exception as e:
    print("⚠️ 시가총액 필터링 실패. 기존 방식으로 진행합니다.", flush=True)
    valid_codes = set()

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
print(f"총 {total_corps}개 상장사 검사를 시작합니다.\n", flush=True)

for idx, corp in enumerate(corp_list): 
    name, dart_code, stock_code = corp['name'], corp['dart_code'], corp['stock_code']
    
    if valid_codes and stock_code not in valid_codes:
        print(f"[{idx+1}/{total_corps}] ⏩ 스킵: {name} (시가총액 미달)", flush=True)
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
                        # 🛡️ 슬리피지 방어: 최근 20일 평균 거래대금 10억 원 미만 컷오프
                        if p_data['avg_trd_val'] < 1000000000:
                            print(f"[{idx+1}/{total_corps}] ⛔ 거래량 스킵: {name} (유동성 부족)", flush=True)
                            continue
                            
                        # 🛡️ 역배열 방어: 주가 상승률 0% 이하 컷오프
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
                        print(f"[{idx+1}/{total_corps}] ✅ 통과: {name} (샤프지수: {p_data['sharpe_ratio']:.2f} / 거래대금: {int(p_data['avg_trd_val']/100000000)}억)", flush=True)
                    else:
                        print(f"[{idx+1}/{total_corps}] ⚠️ 주가 에러: {name}", flush=True)
                else:
                    print(f"[{idx+1}/{total_corps}] ⚠️ 재무 부족: {name}", flush=True)
                    
            elif status == '013':
                pass # 조용한 스킵
            elif status == '020':
                print(f"\n🚨 API 일일 한도 소진. 모인 데이터로 분석합니다.", flush=True)
                break 
                
    except Exception as e:
        pass # 에러 조용히 무시

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
sharpe_vals = [x['sharpe'] for x in raw_data_list] # 이제 단순 주가가 아닌 샤프지수로 랭킹
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
# 모멘텀 랭킹의 기준을 단순 주가(price_mom)에서 샤프지수(sharpe_win)로 완벽하게 교체
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

save_folder = "data_cache"
if not os.path.exists(save_folder): os.makedirs(save_folder)
filename = os.path.join(save_folder, f"AQR_Pro_Edition_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

with open(filename, 'w', encoding='utf-8-sig') as f:
    # 엑셀에서 확인하기 쉽도록 샤프지수와 거래대금(억) 컬럼 추가
    f.write("종목명,최종점수,가치점수,우량점수,모멘텀점수(샤프+이익),샤프지수,거래대금(억)\n")
    for item in sorted(results, key=lambda x: x['score'], reverse=True):
        f.write(f"{item['name']},{item['score']:.4f},{item['val']:.4f},{item['qual']:.4f},{item['mom']:.4f},{item['sharpe']:.2f},{item['trd_val_100m']}\n")
        
print(f"\n🎉 분석 완료! 프로 에디션 엑셀 저장: {filename}", flush=True)