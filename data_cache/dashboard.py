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

@st.cache_data
def load_db_data():
    db_path = r"C:\mybot\data_cache\quant_history.db"
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM kr_quant_ranking", conn)
    conn.close()
    return df

@st.cache_data
def get_krx_mapping():
    krx = fdr.StockListing('KRX')
    return dict(zip(krx['Name'], krx['Code']))

df_main = load_db_data()
name_to_code = get_krx_mapping()

if df_main.empty:
    st.error("❌ DB 데이터를 불러올 수 없습니다. 한미 통합 빌더를 먼저 실행하여 데이터를 적재해주세요.")
else:
    available_dates = sorted(df_main['Date'].unique(), reverse=True)
    latest_date = available_dates[0]
    df_latest = df_main[df_main['Date'] == latest_date].copy()
    
    has_prev_data = len(available_dates) > 1
    if has_prev_data:
        prev_date = available_dates[1]
        df_prev = df_main[df_main['Date'] == prev_date].copy()
    else:
        prev_date = None

    st.markdown(f"**최신 데이터 기준일:** {latest_date} | **시스템 상태:** 실시간 연동 완료")
    st.divider()

    # =========================================================
    # 2. 사이드바: 🎛️ 팩터 가중치 슬라이더
    # =========================================================
    st.sidebar.header("🎛️ 나만의 팩터 비중 조절")
    w_value = st.sidebar.slider("💰 가치(Value) 가중치", 0, 100, 33)
    w_quality = st.sidebar.slider("💎 우량(Quality) 가중치", 0, 100, 33)
    w_momentum = st.sidebar.slider("🚀 모멘텀(Momentum) 가중치", 0, 100, 34)
    
    total_weight = w_value + w_quality + w_momentum
    if total_weight == 0: total_weight = 1
    
    real_w_val = w_value / total_weight
    real_w_qual = w_quality / total_weight
    real_w_mom = w_momentum / total_weight

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
                    