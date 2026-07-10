import streamlit as st
import pandas as pd
import sqlite3
import os
import plotly.graph_objects as go
import FinanceDataReader as fdr

# =========================================================
# 1. 페이지 레이아웃 및 캐싱 설정
# =========================================================
st.set_page_config(page_title="도윤's 고급 퀀트 랩", layout="wide")
st.title("🧪 도윤's 다이내믹 퀀트 랩 (시즌 3: 순위 변동 추적 엔진)")
import FinanceDataReader as fdr

# =======================================================================
# 🚨 [상단 전광판] 실시간 시장 국면 인디케이터 엔진
# =======================================================================
@st.cache_data(ttl=3600) # 1시간마다 한 번씩만 코스피 지수를 새로고침하여 속도 최적화
def get_market_indicator():
    # KOSPI 최근 2년치 데이터 불러오기
    kospi_df = fdr.DataReader('KS11', '2022-01-01')
    
    # 200일 이동평균선 및 최근 60일 고점 대비 낙폭(DD) 계산
    kospi_df['MA200'] = kospi_df['Close'].rolling(window=200).mean()
    kospi_df['Peak60'] = kospi_df['Close'].rolling(window=60).max()
    kospi_df['Drawdown'] = ((kospi_df['Close'] - kospi_df['Peak60']) / kospi_df['Peak60']) * 100
    
    return kospi_df.iloc[-1], kospi_df.iloc[-2] # 최신일과 전일 데이터 반환

try:
    current_data, prev_data = get_market_indicator()
    current_price = current_data['Close']
    prev_price = prev_data['Close']
    ma200_current = current_data['MA200']
    dd_current = current_data['Drawdown']
    
    # 시장 국면 판단 로직
    if current_price < ma200_current or dd_current <= -10.0:
        regime = "공포 국면 😨"
        bg_color = "error"
        advice = "⚠️ 변동성이 커진 하락장입니다. 모멘텀 비중을 낮추고, F-Score가 높은 우량주와 현금 비중 확대를 추천합니다."
    elif current_price > ma200_current * 1.15: # 200일선 대비 15% 이상 과열시
        regime = "과열 국면 🔥"
        bg_color = "warning"
        advice = "📢 시장이 다소 과열되었습니다. 달리는 말(모멘텀)에 올라타되, PCR 등 현금흐름 팩터로 안전판을 확보하세요."
    else:
        regime = "중립 국면 ⚖️"
        bg_color = "info"
        advice = "✅ 평온한 시장입니다. 나만의 세부 가중치 리밸런싱 전략을 유지하기 좋은 타이밍입니다."

    # 화면 렌더링
    st.markdown("### 📡 실시간 시장 국면 레이더")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(label="현재 KOSPI 지수", value=f"{current_price:,.2f}", delta=f"{current_price - prev_price:,.2f}")
    with col2:
        st.metric(label="시장 심리 국면", value=regime)
    with col3:
        st.metric(label="최근 60일 고점 대비 낙폭(DD)", value=f"{dd_current:.2f}%", delta=f"{dd_current:.2f}%")

    # 국면별 맞춤 가이드라인 알림창
    if bg_color == "error":
        st.error(advice)
    elif bg_color == "warning":
        st.warning(advice)
    else:
        st.info(advice)
        
    st.markdown("---") # 아래 랭킹표와의 시각적 분리선

except Exception as e:
    st.warning("현재 실시간 KOSPI 데이터를 불러올 수 없습니다.")
# =======================================================================
@st.cache_data
def load_db_data():
    db_path = "data_cache/quant_history.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM kr_quant_ranking", conn)
    conn.close()
    return df



df_main = load_db_data()

# DB 컬럼 이름을 자동 감지해서 짝지어주는 스마트 로직
name_to_code = {}
if not df_main.empty:
    cols = df_main.columns.tolist()
    # '종목명'이나 'Name'을 자동으로 찾음
    name_col = '종목명' if '종목명' in cols else ('Name' if 'Name' in cols else cols[0])
    # '종목코드'나 'Code'를 자동으로 찾음
    code_col = '종목코드' if '종목코드' in cols else ('Code' if 'Code' in cols else cols[1])
    
    name_to_code = dict(zip(df_main[name_col], df_main[code_col]))

if df_main.empty:
    st.error("❌ DB 데이터를 불러올 수 없습니다. 한미 통합 빌더를 먼저 실행하여 데이터를 적재해주세요.")
else:
    available_dates = sorted(df_main['Date'].unique(), reverse=True)
    latest_date = available_dates[0]
    # drop_duplicates를 추가하여 같은 날짜의 중복 종목을 제거 (가장 마지막에 구워진 데이터만 보존)
    df_latest = df_main[df_main['Date'] == latest_date].drop_duplicates(subset=['종목명'], keep='last').copy()
    
    has_prev_data = len(available_dates) > 1
    if has_prev_data:
        prev_date = available_dates[1]
        df_prev = df_main[df_main['Date'] == prev_date].drop_duplicates(subset=['종목명'], keep='last').copy()
    else:
        prev_date = None

    st.markdown(f"**최신 데이터 기준일:** {latest_date} | **시스템 상태:** 실시간 연동 완료")
    st.divider()

    # =======================================================================
    # 🎛️ [좌측 사이드바] 전문가용 세부 지표 컨트롤러 (100% 자동 보정 엔진)
    # =======================================================================
    st.sidebar.markdown("### 🎛️ 나만의 팩터 설계소")
    market = st.sidebar.radio("🌍 거래소 선택", ["🇰🇷 한국 (KOSPI/KOSDAQ)", "🇺🇸 미국 (NYSE/NASDAQ)"])

    st.sidebar.markdown("#### ■ 1단계: 핵심 팩터 비중 (대분류)")
    w_value = st.sidebar.slider("가치 (Value) 가중치", 0, 100, 50)
    w_quality = st.sidebar.slider("우량 (Quality) 가중치", 0, 100, 30)
    w_momentum = st.sidebar.slider("모멘텀 (Momentum) 가중치", 0, 100, 20)

    # [백엔드 로직 1] 대분류 정규화 계산 (세 슬라이더의 합을 항상 100% 비율로 환산)
    total_macro = w_value + w_quality + w_momentum
    if total_macro > 0:
        real_w_val = w_value / total_macro  # 변수명 유지 (아래 3. 실시간 점수 계산 코드와 호환)
        real_w_qual = w_quality / total_macro
        real_w_mom = w_momentum / total_macro
        
        # 화면 표시용(100분율)
        disp_w_val = real_w_val * 100
        disp_w_qual = real_w_qual * 100
        disp_w_mom = real_w_mom * 100
    else:
        real_w_val = real_w_qual = real_w_mom = 0
        disp_w_val = disp_w_qual = disp_w_mom = 0

    st.sidebar.markdown("#### ■ 2단계: 세부 지표 마이크로 튜닝 (소분류)")

    # ① 가치(Value) 세부 지표 설정
    with st.sidebar.expander("🔽 가치(Value) 세부 지표 비율 설정", expanded=True):
        sub_pcr = st.slider("💡 PCR (영업현금흐름)", 0, 100, 40)
        sub_pbr = st.slider("🏢 PBR (순자산/안전판)", 0, 100, 30)
        sub_ev = st.slider("🤝 EV/EBITDA (총가치)", 0, 100, 20)
        sub_per = st.slider("💰 PER (단기 순이익)", 0, 100, 10)
        
        total_val_sub = sub_pcr + sub_pbr + sub_ev + sub_per
        if total_val_sub > 0:
            final_pcr = (sub_pcr / total_val_sub) * disp_w_val
            final_pbr = (sub_pbr / total_val_sub) * disp_w_val
            final_ev = (sub_ev / total_val_sub) * disp_w_val
            final_per = (sub_per / total_val_sub) * disp_w_val
        else:
            final_pcr = final_pbr = final_ev = final_per = 0

    # ② 우량(Quality) 세부 지표 설정
    with st.sidebar.expander("🔽 우량(Quality) 세부 지표 비율 설정", expanded=False):
        sub_fscore = st.slider("🛡️ F-Score (재무 건전성)", 0, 100, 50)
        sub_roe = st.slider("📈 ROE & ROA (수익성)", 0, 100, 30)
        sub_accruals = st.slider("📉 발생액(Accruals) 비율", 0, 100, 20)
        
        total_qual_sub = sub_fscore + sub_roe + sub_accruals
        if total_qual_sub > 0:
            final_fscore = (sub_fscore / total_qual_sub) * disp_w_qual
            final_roe = (sub_roe / total_qual_sub) * disp_w_qual
            final_accruals = (sub_accruals / total_qual_sub) * disp_w_qual
        else:
            final_fscore = final_roe = final_accruals = 0

    # ③ 모멘텀(Momentum) 세부 지표 설정
    with st.sidebar.expander("🔽 모멘텀(Momentum) 세부 지표 비율 설정", expanded=False):
        sub_price_mom = st.slider("📈 12-1 가격 모멘텀", 0, 100, 60)
        sub_earnings_mom = st.slider("📊 이익 추정치 상향", 0, 100, 40)
        
        total_mom_sub = sub_price_mom + sub_earnings_mom
        if total_mom_sub > 0:
            final_price_mom = (sub_price_mom / total_mom_sub) * disp_w_mom
            final_earnings_mom = (sub_earnings_mom / total_mom_sub) * disp_w_mom
        else:
            final_price_mom = final_earnings_mom = 0

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 🧮 시스템 자동 보정 결과 (총합 100%)")
    st.sidebar.caption(f"**[가치 {disp_w_val:.1f}%]** PCR: {final_pcr:.1f}% | PBR: {final_pbr:.1f}% | EV: {final_ev:.1f}% | PER: {final_per:.1f}%")
    st.sidebar.caption(f"**[우량 {disp_w_qual:.1f}%]** F-Score: {final_fscore:.1f}% | ROE: {final_roe:.1f}% | 발생액: {final_accruals:.1f}%")
    st.sidebar.caption(f"**[모멘텀 {disp_w_mom:.1f}%]** 가격추세: {final_price_mom:.1f}% | 이익상향: {final_earnings_mom:.1f}%")

    total_check = (final_pcr + final_pbr + final_ev + final_per + 
                   final_fscore + final_roe + final_accruals + 
                   final_price_mom + final_earnings_mom)
    st.sidebar.success(f"✅ 백엔드 최종 팩터 결합도: **{total_check:.1f}%**")
    
    # =========================================================
    # 3. 🧠 실시간 점수 및 순위 변동 정밀 계산
    # =========================================================
    df_latest['나만의 맞춤 점수'] = (df_latest['가치점수'] * real_w_val) + \
                                     (df_latest['우량점수'] * real_w_qual) + \
                                     (df_latest['모멘텀점수'] * real_w_mom)
    df_result = df_latest.sort_values(by='나만의 맞춤 점수', ascending=False).reset_index(drop=True)
    df_result.insert(0, '실시간 순위', df_result.index + 1)
    df_top50 = df_result.head(50).copy()

    if has_prev_data:
        df_prev['나만의 맞춤 점수'] = (df_prev['가치점수'] * real_w_val) + \
                                         (df_prev['우량점수'] * real_w_qual) + \
                                         (df_prev['모멘텀점수'] * real_w_mom)
        df_prev_sorted = df_prev.sort_values(by='나만의 맞춤 점수', ascending=False).reset_index(drop=True)
        df_prev_sorted['저번순위'] = df_prev_sorted.index + 1
        prev_rank_map = dict(zip(df_prev_sorted['종목명'], df_prev_sorted['저번순위']))
        
        def track_rank_delta(row):
            name = row['종목명']
            curr_rank = row['실시간 순위']
            if name not in prev_rank_map: return "🆕 신규"
            else:
                delta = prev_rank_map[name] - curr_rank
                if delta > 0: return f"▲{delta}"
                elif delta < 0: return f"▼{abs(delta)}"
                else: return "-"

        df_top50['변동'] = df_top50.apply(track_rank_delta, axis=1)
        st.subheader(f"🏆 실시간 가중치 적용 커스텀 전략 Top 50")
        st.caption(f"💡 비교 기준일({prev_date}) 대비 순위 변동 지표(▲ 상승, ▼ 하락)가 동기화됩니다.")
    else:
        df_top50['변동'] = "데이터 1개"
        st.subheader("🏆 실시간 가중치 적용 커스텀 전략 Top 50")

    display_cols = ['실시간 순위', '변동', '종목명', '나만의 맞춤 점수', '가치점수', '우량점수', '모멘텀점수', '거래대금(억)']
    st.dataframe(df_top50[display_cols], use_container_width=True, hide_index=True)
    
    st.divider()

    # =========================================================
    # 4. 하단 무기 배치: 📊 Step 1 & Step 2
    # =========================================================
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🎯 Step 1: 개별 종목 팩터 X-Ray (상대 비교)")
        selected_stock = st.selectbox("조회할 종목을 선택하세요:", df_result['종목명'].head(50).tolist())
        stock_info = df_result[df_result['종목명'] == selected_stock].iloc[0]
        
        categories = ['가치(Value)', '우량(Quality)', '모멘텀(Momentum)']
        scores = [stock_info['가치점수'], stock_info['우량점수'], stock_info['모멘텀점수']]
        avg_scores = [df_top50['가치점수'].mean(), df_top50['우량점수'].mean(), df_top50['모멘텀점수'].mean()]
        
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(r=avg_scores, theta=categories, fill='none', name='Top 50 평균', line=dict(color='rgba(150, 150, 150, 0.6)', width=2, dash='dash')))
        fig_radar.add_trace(go.Scatterpolar(r=scores, theta=categories, fill='toself', name=selected_stock, line=dict(color='#FF4B4B', width=2), fillcolor='rgba(255, 75, 75, 0.3)'))
        fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 1])), showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), height=380, margin=dict(l=50, r=50, t=30, b=30))
        st.plotly_chart(fig_radar, use_container_width=True)

    with col2:
        st.subheader("🚀 Step 2: 자산 맞춤형 실시간 적립식 백테스터")
        
        # [NEW] 포트폴리오 편입 종목 수 조절 (최대 15% 룰 강제 적용)
        num_stocks = st.slider("🛒 포트폴리오 편입 종목 수 (최대 15% 한도 룰 적용)", min_value=7, max_value=10, value=10, step=1)
        weight_per_stock = 100 / num_stocks
        
        st.caption(f"💡 상위 {num_stocks}개 종목에 각각 **{weight_per_stock:.1f}%**씩 동일 비중으로 분산 투자합니다. (15% 이하 안전 통과✅)")
        
        sub_col1, sub_col2 = st.columns(2)
        with sub_col1:
            input_init = st.number_input("💵 초기 자산 진입 비용 (만원)", min_value=0, value=1000, step=100)
        with sub_col2:
            input_monthly = st.number_input("🐷 매월 추가 적립 비용 (만원)", min_value=0, value=50, step=5)
            
        init_won = input_init * 10000
        monthly_won = input_monthly * 10000
        
        top_n_tickers = df_result['종목명'].head(num_stocks).tolist()
        st.markdown(f"**현재 편입 확정 종목:** \n`{', '.join(top_n_tickers)}`")
        
        if st.button("🔥 개인 맞춤형 1개년 시뮬레이션 가동"):
            with st.spinner("주가 데이터를 분석하여 적립식 매매 시뮬레이션 중..."):
                prices = pd.DataFrame()
                for name in top_n_tickers:
                    code = name_to_code.get(name)
                    if code:
                        try:
                            df_p = fdr.DataReader(code, '2025-07-01', '2026-07-01')['Close']
                            prices[name] = df_p
                        except:
                            continue
                
                if not prices.empty:
                    prices = prices.sort_index().ffill().bfill()
                    daily_returns = prices.pct_change().mean(axis=1).fillna(0)
                    
                    current_asset = init_won
                    asset_history = []
                    total_invested = init_won
                    last_month = None
                    
                    for date, d_ret in daily_returns.items():
                        current_asset *= (1 + d_ret)
                        current_month = date.month
                        if last_month is not None and current_month != last_month:
                            current_asset += monthly_won
                            total_invested += monthly_won
                        last_month = current_month
                        asset_history.append(current_asset)
                    
                    portfolio_asset_manwon = pd.Series(asset_history, index=prices.index) / 10000
                    
                    fig_line = go.Figure()
                    fig_line.add_trace(go.Scatter(x=portfolio_asset_manwon.index, y=portfolio_asset_manwon.values, mode='lines', name='나의 실전 총자산', line=dict(color='#00CC96', width=2.5)))
                    fig_line.update_layout(xaxis_title="날짜", yaxis_title="총 자산 가치 (만원)", height=290, margin=dict(l=40, r=40, t=20, b=20), hovermode="x unified")
                    st.plotly_chart(fig_line, use_container_width=True)
                    
                    final_asset_won = current_asset
                    net_profit_won = final_asset_won - total_invested
                    roi_pct = (net_profit_won / total_invested) * 100
                    
                    st.info(
                        f"📊 **시뮬레이션 정산서** \n"
                        f"• 총 누적 원금: **{total_invested/10000:,.0f} 만원** (초기 {input_init}만 + 매월 {input_monthly}만 적립)  \n"
                        f"• 최근 1년 최종 평가액: **{final_asset_won/10000:,.0f} 만원** \n"
                        f"• 순수익: **{net_profit_won/10000:+,.0f} 만원** (수익률: **{roi_pct:+.2f}%**)"
                    )
                else:
                    st.warning("과거 주가 데이터를 가져오지 못했습니다.")
