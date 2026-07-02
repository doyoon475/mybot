# 삼성전자 데이터(ROE 기반)와 실시간 주가(PBR 계산용)를 합치는 퀀트 맛보기 코드
print(">> 퀀트 봇: 삼성전자 데이터를 분석 중...")

# (지난번 성공한 맨손 다이렉트 로직을 활용해 ROE와 자산 데이터를 가져옵니다)
# 자산 총계와 당기순이익은 지난번 결과값을 일단 상수로 활용해 시뮬레이션합니다.
total_equity = 436320337000000 
net_income = 45206805000000
roe = (net_income / total_equity) * 100

# 퀀트 핵심: PBR 계산 (시가총액 / 자본총계)
# 삼성전자 주식 수(대략 5,969,782,550주)를 이용해 시가총액 계산
market_price = 75000  # 예시 가격 (실시간 가격을 여기에 연동 가능)
market_cap = market_price * 5969782550
pbr = market_cap / total_equity

print(f"\n=== 퀀트 분석 리포트 ===")
print(f"ROE: {roe:.2f}%")
print(f"PBR: {pbr:.2f}배")

if roe > 10 and pbr < 1.0:
    print("\n[매수 신호] 이 기업은 우량하고 저평가되어 있습니다! 매수 고려!")
elif roe > 10:
    print("\n[관망] 우량한 기업이지만, 지금은 조금 비쌉니다.")
else:
    print("\n[매도/보류] ROE가 낮아 투자가치가 떨어집니다.")