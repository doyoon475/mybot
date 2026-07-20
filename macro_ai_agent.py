import os
import json
import requests
import google.generativeai as genai
from dotenv import load_dotenv

# ==========================================
# 1. 안전한 환경 변수(API Key) 로드
# ==========================================
# 프로젝트 최상단에 있는 .env 파일에서 키를 불러옵니다.
# .env 파일 예시: 
# PERPLEXITY_API_KEY="pplx-xxx"
# GEMINI_API_KEY="AIzaSy-xxx"
load_dotenv()
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def get_monthly_factor_weights():
    """
    Perplexity로 글로벌 거시경제를 요약하고, Gemini로 재무/세무 딥다이브 분석을 수행하여
    이번 달 최적의 팩터 비중(가치, 우량, 모멘텀)을 총합 100의 JSON 형태로 파싱하여 반환합니다.
    """
    
    # ---------------------------------------------------------
    # 단계 1: Perplexity API 연동 (글로벌 매크로 및 산업 리서치)
    # ---------------------------------------------------------
    print("[1/2] Perplexity AI: 글로벌 매크로 및 이슈 리서치 중...")
    try:
        url = "https://api.perplexity.ai/chat/completions"
        headers = {
            "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "sonar-pro", # 최신 리서치 및 검색 특화 모델
            "messages": [
                {
                    "role": "system", 
                    "content": (
                        "너는 글로벌 거시경제, 최신 퀀트 학술 논문, 그리고 기업 공시 데이터를 종합적으로 분석하는 최고 퀀트 전략가이자 재무/회계 전문가다. "
                        "감정적인 서술을 배제하고, 철저히 객관적인 팩트와 수치, 그리고 논리적 인과관계를 바탕으로 압축해서 브리핑하라."
                    )
                },
                {
                    "role": "user", 
                    "content": (
                        "최근 1달간의 시장 동향을 다음 3가지 관점에서 깊이 있게 리서치하고 핵심만 요약해 줘.\n\n"
                        "1. 학술 및 리서치 동향: SSRN, NBER 등 주요 학술 기관이나 글로벌 IB에서 발표된 최신 퀀트 투자 논문 및 리포트의 핵심 인사이트.\n"
                        "2. 글로벌 매크로 및 금리: 주요국 중앙은행의 금리 동향, 인플레이션 지표 및 핵심 경제 지표의 변화.\n"
                        "3. 상장사 핵심 공시 및 재무/세무 동향: 최근 1달 내 주요 상장사들의 M&A, 자본금 변동, 배당 정책 변화, 또는 시장에 영향을 미칠 만한 주요 회계/세무적 이슈.\n\n"
                        "위 세 가지 데이터를 바탕으로 현재 시장을 관통하는 하나의 '핵심 팩터 내러티브(가치, 우량, 모멘텀 중 무엇이 유리한지)'를 3문단 이내로 도출해라."
                    )
                }
            ]
        }
        
        pplx_response = requests.post(url, json=payload, headers=headers, timeout=30)
        pplx_response.raise_for_status()
        macro_report = pplx_response.json()['choices'][0]['message']['content']
        print("리서치 완료.")
        
    except Exception as e:
        print(f"Perplexity API 에러 발생: {e}")
        # 침묵의 에러 방어: 실패 시 균등 비중 반환
        return {"value": 34, "quality": 33, "momentum": 33, "reason": "매크로 리서치 실패로 인한 시스템 기본 균일 비중 할당"}

    # ---------------------------------------------------------
    # 단계 2: Gemini API 연동 (재무/세무 딥다이브 기반 비중 산출)
    # ---------------------------------------------------------
    print("[2/2] Gemini 3.1 Pro: 재무/세무 관점 분석 및 비중 JSON 도출 중...")
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 🚨 시니어의 최적화 포인트: CTA 1차 수준의 엄밀함 부여 및 JSON 강제 출력 (Progressive Disclosure)
        system_instruction = (
            "당신은 세무사(CTA) 1차 시험 객관식 수준의 빠르고 정확한 회계 및 세무 지식을 갖춘 15년 차 시니어 퀀트 전략가입니다. "
            "주어진 글로벌 거시경제 리포트를 바탕으로 재무/세무 딥다이브 관점에서 분석하여, "
            "이번 달 주식 시장에 가장 적합한 [가치(Value), 우량(Quality), 모멘텀(Momentum)] 팩터의 비중을 결정하십시오. "
            "비중은 반드시 정수여야 하며 세 팩터의 합은 무조건 100이어야 합니다. "
            "응답은 오직 아래 JSON 형식으로만 출력하십시오. 코드 블록(```json)이나 다른 텍스트를 일절 덧붙이지 마십시오.\n"
            '{"value": 40, "quality": 40, "momentum": 20, "reason": "여기에 한 줄 요약 사유 작성"}'
        )
        
        # generation_config를 통해 결과물을 완벽한 JSON 형식으로 강제 파싱되도록 락(Lock)을 겁니다.
        model = genai.GenerativeModel(
            model_name="gemini-3.1-pro-preview",
            system_instruction=system_instruction,
            generation_config={"response_mime_type": "application/json"} 
        )
        
        prompt = f"다음은 최근 1달간의 글로벌 매크로 리포트입니다.\n\n{macro_report}\n\n이 리포트를 바탕으로 최적의 팩터 비중 JSON을 즉시 반환하십시오."
        
        gemini_response = model.generate_content(prompt)
        
        # JSON 텍스트 파싱을 위해 불필요한 마크다운 백틱 등 전처리
        raw_text = gemini_response.text.strip()
        
        # 정규표현식을 사용해 처음 나타나는 { 부터 } 까지의 문자열만 추출
        import re
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            raw_text = match.group(0)
            
        print(f"[DEBUG] Gemini Raw Response:\n{raw_text}")
        
        # JSON 텍스트를 파이썬 딕셔너리로 완벽 변환
        result = json.loads(raw_text)
        
        # 안전장치: 합이 100인지 검증 (에러 시 방어 로직으로 빠짐)
        total_weight = result.get('value', 0) + result.get('quality', 0) + result.get('momentum', 0)
        if total_weight != 100:
            raise ValueError(f"팩터 비중의 합이 {total_weight}입니다. (100이어야 함)")
            
        print("최적 비중 산출 완료.")
        return result
        
    except Exception as e:
        print(f"Gemini API 또는 JSON 파싱 에러 발생: {e}")
        return {"value": 34, "quality": 33, "momentum": 33, "reason": "AI 분석 실패 또는 JSON 파싱 에러로 인한 기본 비중 할당"}

# 단독 실행 테스트용
if __name__ == "__main__":
    final_weights = get_monthly_factor_weights()
    print(f"\n[최종 산출된 팩터 비중]\n{json.dumps(final_weights, ensure_ascii=False, indent=2)}")