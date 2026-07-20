import os
import time
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

try:
    import OpenDartReader
except ImportError:
    print("⚠️ OpenDartReader 라이브러리가 설치되어 있지 않습니다. 터미널에서 'pip install OpenDartReader'를 실행해 주세요.")
    OpenDartReader = None

# ==========================================
# 💡 15년 차 시니어의 철학: 확장성을 고려한 DART 계정과목 표준화 MAPPING 룰
# 향후 복잡한 XBRL(국제표준재무보고) 계정과목 명칭들을 우리 내부 DB(월별 팩터)의 표준 명칭으로 통일하기 위한 뼈대입니다.
# ==========================================
DART_ACCOUNT_MAPPING = {
    # 예시: '유동자산': 'current_assets',
    #       '매출액': 'revenue',
    #       '영업이익': 'operating_profit',
    # 향후 실무 분석을 거치며 점진적으로 추가될 예정입니다.
}

# ==========================================
# 1. 안전한 환경 변수 로드 및 DART 객체 초기화
# ==========================================
load_dotenv()
DART_API_KEY = os.getenv("DART_API_KEY")

if not DART_API_KEY:
    print("⚠️ [경고] .env 파일에 DART_API_KEY가 설정되지 않았습니다. DART 개발자 센터에서 키를 발급받아 추가해 주세요.")

try:
    if DART_API_KEY and OpenDartReader:
        dart = OpenDartReader(DART_API_KEY)
    else:
        dart = None
except Exception as e:
    print(f"❌ DART API 객체 초기화 중 에러 발생: {e}")
    dart = None

# ==========================================
# 2. 핵심 수집 로직: 특정 기업 최근 재무제표 호출 함수
# ==========================================
def fetch_recent_financials(ticker):
    """
    OpenDartReader를 사용하여 주어진 종목코드(ticker)의 가장 최근 연간 사업보고서
    (재무상태표, 손익계산서 등) 데이터를 DataFrame으로 안전하게 추출합니다.
    """
    # 2026년 현재 시점 기준, 가장 최신 확정 연간보고서는 작년(2025년) 데이터일 확률이 높습니다.
    # 유동적인 조회를 위해 오늘 기준 작년 연도를 기본값으로 설정합니다.
    target_year = datetime.today().year - 1
    
    print(f"📡 [DART API 호출] 종목코드 '{ticker}'의 {target_year}년도 연간 사업보고서 데이터 요청 중...")
    
    if not dart:
        print("❌ DART API가 초기화되지 않았습니다. API 키 및 라이브러리 설치 상태를 확인해 주세요.")
        return pd.DataFrame()

    # 🚨 DART API 호출 제한(Rate Limit) 방어 로직 (시니어의 안정성 철학)
    # 하루 10,000건 및 분당 제한을 피하기 위해 호출 전 최소 1초 대기하여 트래픽을 분산시킵니다.
    time.sleep(1)

    try:
        # reprt_code='11011' : 사업보고서 (연간)
        # finstate 메서드는 재무상태표, 손익계산서 등 주요 재무 지표를 모두 가져옵니다.
        df_fin = dart.finstate(corp=ticker, bsns_year=target_year, reprt_code='11011')
        
        if df_fin is None or df_fin.empty:
            print(f"⚠️ [데이터 없음] '{ticker}'의 {target_year}년도 재무 데이터가 DART에 존재하지 않거나 조회가 불가합니다.")
            return pd.DataFrame()
        
        print(f"✅ [조회 성공] '{ticker}' 재무 데이터 {len(df_fin)}건 수집 완료!")
        
        # API 무리한 호출 방지를 위한 안전 후속 딜레이
        time.sleep(0.5)
        
        return df_fin

    except Exception as e:
        # 시스템 뻗음(Crash) 방지 (Graceful degradation)
        print(f"❌ [API 호출 에러] '{ticker}' 데이터 수집 중 치명적인 문제가 발생했습니다.")
        print(f"   ㄴ 에러 상세: {e}")
        return pd.DataFrame()

# ==========================================
# 3. 단독 실행 테스트 로직
# ==========================================
if __name__ == "__main__":
    # 테스트용: 삼성전자(005930) 가장 최근 실적 조회
    test_ticker = "005930"
    
    df_result = fetch_recent_financials(test_ticker)
    
    if not df_result.empty:
        print(f"\n📊 [데이터 미리보기 - {test_ticker}]\n")
        # sj_nm(재무제표명), account_nm(계정명), thstrm_nm(당기명), thstrm_amount(당기금액)
        display_cols = ['sj_nm', 'account_nm', 'thstrm_nm', 'thstrm_amount']
        
        # 보기 좋게 일부 데이터만 출력
        try:
            print(df_result[display_cols].head(10))
            print("\n💡 힌트: 이제 이 추출된 계정명(account_nm)들을 DART_ACCOUNT_MAPPING에 하나씩 매핑해 나가면 됩니다!")
        except Exception as e:
            print("데이터 출력 중 에러 (컬럼 미스매치 등):", e)
