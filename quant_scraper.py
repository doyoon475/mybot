import os
import time
import random
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def run_quant_crawler(start_page=1, end_page=10):
    print("🚀 [퀀트 데이터 자동 크롤러] 프로그램을 시작합니다.")
    
    # 1. 다운로드 폴더 설정 (절대 경로)
    download_dir = os.path.abspath("./quant_raw_data")
    os.makedirs(download_dir, exist_ok=True)
    print(f"📁 다운로드 저장 경로: {download_dir}")

    # 2. 크롬 브라우저 옵션 설정 (자동 다운로드 경로 지정)
    chrome_options = Options()
    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,  # 다운로드 창 띄우지 않고 즉시 저장
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    # 봇 탐지 우회 옵션 (자동화 제어 메시지 숨김)
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # 3. 드라이버 실행
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # 4. 사이트 접속 및 수동 로그인 대기 (1분)
        base_url = "https://quantking.net/membership/list?page=1"
        driver.get(base_url)
        
        print("\n⏳ [수동 로그인 대기] 브라우저 창에서 직접 로그인을 진행해 주세요.")
        print("⏳ 60초 뒤에 자동으로 크롤링이 시작됩니다...")
        
        # 남은 시간 표시
        for i in range(60, 0, -10):
            print(f"   남은 시간: {i}초...")
            time.sleep(10)
            
        print("\n🔥 로그인이 완료된 것으로 간주하고 자동 탐색을 시작합니다!")

        # 5. 페이지 순회 (지정된 시작 페이지부터 종료 페이지까지)
        for page in range(start_page, end_page + 1):
            page_url = f"https://quantking.net/membership/list?page={page}"
            driver.get(page_url)
            time.sleep(random.uniform(1.5, 2.5)) # 페이지 로딩 딜레이 (속도 향상)
            
            print(f"\n📄 [페이지 {page}/{end_page}] 게시물 스캔 중...")
            
            try:
                # React/Vue 등의 SPA 환경에서 href가 없는 경우를 대비한 완전한 텍스트 기반 클릭 스크래핑
                # 1. 화면에 렌더링된 요소 중 '퀀트데이터' 글자가 들어간 텍스트 덩어리를 모두 수집
                elements = driver.find_elements(By.XPATH, "//*[contains(text(), '퀀트데이터') or contains(text(), '퀀트 데이터')]")
                
                post_texts = []
                for el in elements:
                    text = el.text.strip()
                    # 제목처럼 긴 텍스트만 추출 (메뉴 이름 등 오탐 방지)
                    if text and len(text) > 10 and text not in post_texts:
                        post_texts.append(text)
                        
                print(f"      [디버깅] 클릭 가능한 게시물 제목 개수: {len(post_texts)}")
                
                if not post_texts:
                    print(f"🔍 [페이지 {page}] '퀀트데이터' 관련 게시물이 없습니다. 다음 페이지로 넘어갑니다.")
                    continue
                    
            except Exception as e:
                print(f"❌ [페이지 {page}] 목록 파싱 에러 발생: {e}")
                continue

            print(f"🔍 [페이지 {page}] 총 {len(post_texts)}개 게시물 순차 다운로드 시작!")

            # 6. 각 게시물 상세 페이지로 이동하여 첨부파일 다운로드
            for idx, title_text in enumerate(post_texts, 1):
                try:
                    # 안전을 위해 매 글을 클릭하기 전에 목록 페이지를 확실히 새로고침 (Stale 방지)
                    if idx > 1:
                        driver.get(page_url)
                        time.sleep(random.uniform(1.0, 2.0)) # (속도 향상)
                    
                    # 제목 텍스트로 요소를 찾아 강제 클릭 (Javascript 기반 라우팅 뚫기)
                    safe_title = title_text.replace("'", "").replace('"', '')
                    target_element = driver.find_element(By.XPATH, f"//*[contains(text(), '{safe_title}')]")
                    driver.execute_script("arguments[0].click();", target_element)
                    
                    time.sleep(random.uniform(1.5, 2.5)) # 상세 페이지 진입 대기 (속도 향상)
                    
                    # 첨부파일 다운로드 버튼 찾기 및 강제 클릭
                    # 상세 페이지 구조 역시 알 수 없으므로 확장자 텍스트(.xlsx, .csv 등)를 직접 타겟팅
                    download_links = driver.find_elements(By.XPATH, "//*[contains(text(), '.csv') or contains(text(), '.xlsx') or contains(text(), '.zip')]")
                    
                    if download_links:
                        driver.execute_script("arguments[0].click();", download_links[0])
                        print(f"  ✔️ [페이지 {page}] {idx}/{len(post_texts)} 다운로드 완료: {title_text[:20]}...")
                        time.sleep(random.uniform(2.0, 3.5)) # 파일이 다운로드될 시간 대기 (속도 향상)
                    else:
                        print(f"  ⚠️ [페이지 {page}] {idx}/{len(post_texts)} 첨부파일을 찾지 못했습니다: {title_text[:20]}...")
                        
                except Exception as e:
                    print(f"  ❌ [페이지 {page}] {idx}/{len(post_texts)} 처리 중 에러: {title_text[:15]}")
                    
    except Exception as e:
        print(f"\n🚨 치명적 에러로 프로그램이 중단되었습니다: {e}")
        
    finally:
        print("\n🛑 크롤링 작업이 모두 종료되었습니다. 브라우저를 닫습니다.")
        driver.quit()

if __name__ == "__main__":
    # 21페이지부터 176페이지까지 탐색 (속도를 높여서 빠른 다운로드 진행)
    run_quant_crawler(start_page=21, end_page=176)