import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# ==========================================
# 1. 초기 UI 및 Session State(메모리) 설정
# ==========================================
st.set_page_config(page_title="초고속 퀀트 대시보드", layout="wide")
st.title("🧪 다이내믹 퀀트 랩 V2 (실전 백테스트 엔진)")
st.caption("SQLite 고속 DB 기반 | 점진적 공개(Progressive Disclosure) UI 적용")

if 'step1_unlocked' not in st.session_state:
    st.session_state.step1_unlocked = False
if 'step2_unlocked' not in st.session_state:
    st.session_state.step2_unlocked = False
if 'w_val' not in st.session_state:
    st.session_state.w_val = 40
if 'w_qual' not in st.session_state:
    st.session_state.w_qual = 40
if 'w_mom' not in st.session_state:
    st.session_state.w_mom = 20
if 'ai_reason' not in st.session_state:
    st.session_state.ai_reason = ""

def reset_ui_state():
    st.session_state.step1_unlocked = False
    st.session_state.step2_unlocked = False

# ==========================================
# 2. 초고속 DB 로드 (캐시 만료 시간 1시간 설정)
# ==========================================
@st.cache_data(ttl=3600)
def load_db_data():
    conn = sqlite3.connect('data_cache/quant_history.db')
    
    query_factor = """
        SELECT f.date, f.ticker, m.name as '종목명', m.sector as '섹터', 
               f.per, f.pbr, f.psr, f.ev_ebitda, f.roe, f.op_margin, f.gross_margin, 
               f.f_score, f.mom_1m, f.mom_6m, f.mom_12m
        FROM monthly_factor f
        JOIN stock_master m ON f.ticker = m.ticker
        WHERE m.is_active = 1
    """
    df_factor = pd.read_sql(query_factor, conn)
    
    query_price = "SELECT date, ticker, close FROM daily_price"
    try:
        df_price = pd.read_sql(query_price, conn)
        if not df_price.empty:
            df_price['date'] = pd.to_datetime(df_price['date'])
            df_price['month'] = df_price['date'].dt.to_period('M')
            df_monthly_price = df_price.sort_values('date').groupby(['month', 'ticker']).last().reset_index()
            df_monthly_price['date'] = df_monthly_price['month'].dt.strftime('%Y-%m')
        else:
            df_monthly_price = pd.DataFrame()
    except:
        df_monthly_price = pd.DataFrame()
        
    conn.close()
    return df_factor, df_monthly_price

df_all, df_price_all = load_db_data()

if df_all.empty:
    st.error("❌ DB 데이터가 없습니다. 터미널에서 'python quant_etl.py'를 먼저 실행해 주세요.")
    st.stop()

latest_date = df_all['date'].max()
df_main = df_all[df_all['date'] == latest_date].copy()

# ==========================================
# 3. 🎛️ 좌측 사이드바: 팩터 설계소
# ==========================================
st.sidebar.markdown("### 🎛️ 나만의 팩터 설계소")

if st.sidebar.button("🤖 AI 매크로 비중 자동 할당", type="primary", use_container_width=True):
    with st.spinner("글로벌 매크로 분석 및 비중 계산 중... (약 10~20초 소요)"):
        from macro_ai_agent import get_monthly_factor_weights
        ai_weights = get_monthly_factor_weights()
        st.session_state.w_val = ai_weights.get('value', 34)
        st.session_state.w_qual = ai_weights.get('quality', 33)
        st.session_state.w_mom = ai_weights.get('momentum', 33)
        st.session_state.ai_reason = ai_weights.get('reason', '')
        reset_ui_state()
        st.rerun()

w_value = st.sidebar.slider("가치 (Value)", 0, 100, st.session_state.w_val, key='w_val', on_change=reset_ui_state)
w_quality = st.sidebar.slider("우량 (Quality)", 0, 100, st.session_state.w_qual, key='w_qual', on_change=reset_ui_state)
w_momentum = st.sidebar.slider("모멘텀 (Momentum)", 0, 100, st.session_state.w_mom, key='w_mom', on_change=reset_ui_state)

if st.session_state.ai_reason:
    st.sidebar.markdown("💡 **AI 팩터 분석 완료 (상세 보기 Hover)**", help=st.session_state.ai_reason)

total_macro = w_value + w_quality + w_momentum
if total_macro > 0:
    real_w_val, real_w_qual, real_w_mom = w_value / total_macro, w_quality / total_macro, w_momentum / total_macro
else:
    real_w_val = real_w_qual = real_w_mom = 0

with st.sidebar.expander("🔽 가치(Value) 세부 비중", expanded=False):
    sub_per = st.slider("PER (순이익)", 0, 100, 30, on_change=reset_ui_state)
    sub_pbr = st.slider("PBR (순자산)", 0, 100, 30, on_change=reset_ui_state)
    sub_psr = st.slider("PSR (매출액)", 0, 100, 20, on_change=reset_ui_state)
    sub_ev = st.slider("EV/EBITDA", 0, 100, 20, on_change=reset_ui_state)
    
    tot_val_sub = sub_per + sub_pbr + sub_psr + sub_ev
    f_per, f_pbr, f_psr, f_ev = [x / tot_val_sub * real_w_val if tot_val_sub > 0 else 0 for x in (sub_per, sub_pbr, sub_psr, sub_ev)]

with st.sidebar.expander("🔽 우량(Quality) 세부 비중", expanded=False):
    sub_roe = st.slider("ROE (자본수익률)", 0, 100, 40, on_change=reset_ui_state)
    sub_opm = st.slider("OPM (영업이익률)", 0, 100, 20, on_change=reset_ui_state)
    sub_gpm = st.slider("GPM (매출총이익률)", 0, 100, 20, on_change=reset_ui_state)
    sub_fscore = st.slider("F-Score (재무건전성)", 0, 100, 20, on_change=reset_ui_state)
    
    tot_qual_sub = sub_roe + sub_opm + sub_gpm + sub_fscore
    f_roe, f_opm, f_gpm, f_fscore = [x / tot_qual_sub * real_w_qual if tot_qual_sub > 0 else 0 for x in (sub_roe, sub_opm, sub_gpm, sub_fscore)]

with st.sidebar.expander("🔽 모멘텀(Momentum) 세부 비중", expanded=False):
    sub_mom1 = st.slider("1개월 등락률", 0, 100, 20, on_change=reset_ui_state)
    sub_mom6 = st.slider("6개월 등락률", 0, 100, 40, on_change=reset_ui_state)
    sub_mom12 = st.slider("12개월 등락률", 0, 100, 40, on_change=reset_ui_state)
    
    tot_mom_sub = sub_mom1 + sub_mom6 + sub_mom12
    f_mom1, f_mom6, f_mom12 = [x / tot_mom_sub * real_w_mom if tot_mom_sub > 0 else 0 for x in (sub_mom1, sub_mom6, sub_mom12)]

# ==========================================
# 4. 랭킹 연산 엔진
# ==========================================
def calculate_rank(df):
    val_rank = (
        df['per'].rank(ascending=True) * f_per +
        df['pbr'].rank(ascending=True) * f_pbr +
        df['psr'].rank(ascending=True) * f_psr +
        df['ev_ebitda'].rank(ascending=True) * f_ev
    )
    qual_rank = (
        df['roe'].rank(ascending=False) * f_roe +
        df['op_margin'].rank(ascending=False) * f_opm +
        df['gross_margin'].rank(ascending=False) * f_gpm +
        df['f_score'].rank(ascending=False) * f_fscore
    )
    mom_rank = (
        df['mom_1m'].rank(ascending=False) * f_mom1 +
        df['mom_6m'].rank(ascending=False) * f_mom6 +
        df['mom_12m'].rank(ascending=False) * f_mom12
    )
    
    df['Total_Rank_Score'] = val_rank + qual_rank + mom_rank
    return df.sort_values(by='Total_Rank_Score', ascending=True).reset_index(drop=True)

df_result = calculate_rank(df_main.copy())
df_result.insert(0, '순위', df_result.index + 1)

# ==========================================
# 5. 점진적 공개(Progressive Disclosure) UI
# ==========================================
st.markdown(f"### 📊 전략 요약 (기준월: {latest_date})")
col1, col2, col3, col4 = st.columns(4)
col1.metric("분석 대상 종목", f"{len(df_result):,} 개")
col2.metric("가치 비중", f"{real_w_val*100:.0f}%")
col3.metric("우량 비중", f"{real_w_qual*100:.0f}%")
col4.metric("모멘텀 비중", f"{real_w_mom*100:.0f}%")

st.divider()

if st.button("🚀 실시간 상위 20종목 포트폴리오 추출", type="primary", width="stretch"):
    st.session_state.step1_unlocked = True
    st.session_state.step2_unlocked = False 

if st.session_state.step1_unlocked:
    with st.expander("🔽 Top 20 종목 상세 리스트", expanded=True):
        display_cols = ['순위', '종목명', '섹터', 'per', 'roe', 'mom_6m', 'mom_12m', 'Total_Rank_Score']
        show_df = df_result.head(20)[display_cols].copy()
        show_df['Total_Rank_Score'] = show_df['Total_Rank_Score'].round(2)
        st.dataframe(show_df, width="stretch", hide_index=True)
    
    st.divider()
    st.markdown("### 📈 Step 2: 실전 다이내믹 시계열 백테스터")
    st.info("💡 **알림**: 과거 팩터 데이터가 1개월 치만 존재하여, **현재 도출된 상위 종목들을 과거 10년 전부터 매월 적립식으로 투자했을 때**의 성과(정적 포트폴리오)를 시뮬레이션합니다.")
    st.caption("✔️ 투자 룰: 1~10위 매수 / 11~20위 유지 (최대 비중 15% 캡) / 21위 밖 전량 매도")
    st.caption("💸 수수료 및 슬리피지: 매수 시 0.15%, 매도 시 0.30% (세금 포함) 적용")
    
    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        init_cap = st.number_input("초기 자본금 (만원)", 100, 100000, 1000, step=100)
    with bc2:
        monthly_cap = st.number_input("매월 적립금 (만원)", 0, 1000, 50, step=10)
    with bc3:
        invest_years = st.slider("투자 기간 (년)", 1, 10, 10)

    if st.button("🔥 10년 실전 백테스트 가동", width="stretch"):
        st.session_state.step2_unlocked = True

    if st.session_state.step2_unlocked:
        if df_price_all.empty:
            st.error("⚠️ 주가 데이터가 없습니다. 터미널에서 `python price_etl.py`를 실행하여 10년 치 주가 데이터를 적재한 뒤 아래 버튼을 눌러 캐시를 초기화하세요.")
            if st.button("🔄 시스템 캐시 메모리 초기화", width="stretch"):
                st.cache_data.clear()
                st.rerun()
        else:
            with st.spinner("10년 치 주가 및 팩터 가중치 기반 다이내믹 리밸런싱을 연산 중입니다..."):
                
                FEE_BUY = 0.0015
                FEE_SELL = 0.0030
                CAP_LIMIT = 0.15
                
                df_history = df_all.copy()
                val_hist = df_history.groupby('date')['per'].rank(ascending=True) * f_per + \
                           df_history.groupby('date')['pbr'].rank(ascending=True) * f_pbr + \
                           df_history.groupby('date')['psr'].rank(ascending=True) * f_psr + \
                           df_history.groupby('date')['ev_ebitda'].rank(ascending=True) * f_ev
                qual_hist = df_history.groupby('date')['roe'].rank(ascending=False) * f_roe + \
                            df_history.groupby('date')['op_margin'].rank(ascending=False) * f_opm + \
                            df_history.groupby('date')['gross_margin'].rank(ascending=False) * f_gpm + \
                            df_history.groupby('date')['f_score'].rank(ascending=False) * f_fscore
                mom_hist = df_history.groupby('date')['mom_1m'].rank(ascending=False) * f_mom1 + \
                           df_history.groupby('date')['mom_6m'].rank(ascending=False) * f_mom6 + \
                           df_history.groupby('date')['mom_12m'].rank(ascending=False) * f_mom12
                
                df_history['Total_Rank_Score'] = val_hist + qual_hist + mom_hist
                df_history['Rank'] = df_history.groupby('date')['Total_Rank_Score'].rank(ascending=True, method='first')
                
                # 투자 기간(년) 슬라이더에 따른 날짜 슬라이싱
                all_dates = sorted(df_price_all['date'].unique())
                max_date = pd.to_datetime(all_dates[-1])
                start_date_str = (max_date - pd.DateOffset(years=invest_years)).strftime('%Y-%m')
                available_dates = [d for d in all_dates if d >= start_date_str]
                
                price_pivot = df_price_all.pivot(index='date', columns='ticker', values='close').ffill().fillna(0)
                
                cash = init_cap * 10000
                portfolio = {}
                asset_history = []
                invested_history = []
                date_history = []
                total_invested = cash
                
                first_buy_price = {} # 종목별 최초 매수 단가 기록
                
                for date in available_dates:
                    if date not in price_pivot.index: continue
                    current_prices = price_pivot.loc[date]
                    
                    if date != available_dates[0]:
                        cash += monthly_cap * 10000
                        total_invested += monthly_cap * 10000
                    
                    stock_value = sum(portfolio[t] * current_prices.get(t, 0) for t in portfolio.keys())
                    total_asset = cash + stock_value
                    
                    # 과거 팩터가 없으면 가장 최신 팩터(현재 기준)의 랭킹을 고정으로 사용
                    monthly_data = df_history[df_history['date'] == date]
                    if monthly_data.empty:
                        monthly_data = df_history[df_history['date'] == df_history['date'].max()]
                    top_10 = monthly_data[monthly_data['Rank'] <= 10]['ticker'].tolist()
                    mid_10 = monthly_data[(monthly_data['Rank'] > 10) & (monthly_data['Rank'] <= 20)]['ticker'].tolist()
                    
                    for t in list(portfolio.keys()):
                        price = current_prices.get(t, 0)
                        if price == 0: continue
                        weight = (portfolio[t] * price) / total_asset if total_asset > 0 else 0
                        
                        if t not in top_10 and t not in mid_10:
                            cash += portfolio[t] * price * (1 - FEE_SELL)
                            del portfolio[t]
                        elif t in mid_10 and weight > CAP_LIMIT:
                            excess_value = (weight - CAP_LIMIT) * total_asset
                            sell_shares = int(excess_value / price)
                            if sell_shares > 0:
                                cash += sell_shares * price * (1 - FEE_SELL)
                                portfolio[t] -= sell_shares
                    
                    stock_value = sum(portfolio[t] * current_prices.get(t, 0) for t in portfolio.keys())
                    total_asset = cash + stock_value
                    target_weight = 0.10
                    
                    for t in top_10:
                        price = current_prices.get(t, 0)
                        if price == 0: continue
                        current_weight = (portfolio.get(t, 0) * price) / total_asset if total_asset > 0 else 0
                        if current_weight < target_weight:
                            buy_value = (target_weight - current_weight) * total_asset
                            actual_buy = min(buy_value, cash)
                            if actual_buy > price:
                                buy_shares = int(actual_buy / (price * (1 + FEE_BUY)))
                                portfolio[t] = portfolio.get(t, 0) + buy_shares
                                cash -= buy_shares * price * (1 + FEE_BUY)
                                
                                # 최초 매수 시 해당 단가를 기록
                                if t not in first_buy_price:
                                    first_buy_price[t] = price
                    
                    final_stock_value = sum(portfolio[t] * current_prices.get(t, 0) for t in portfolio.keys())
                    date_history.append(pd.to_datetime(date))
                    asset_history.append(cash + final_stock_value)
                    invested_history.append(total_invested)

                df_asset = pd.DataFrame({
                    'Total_Value': asset_history,
                    'Total_Invested': invested_history
                }, index=date_history)
                final_val = df_asset['Total_Value'].iloc[-1]
                years = len(df_asset) / 12
                cagr = ((final_val / total_invested) ** (1 / years) - 1) * 100 if years > 0 else 0
                
                df_asset['HWM'] = df_asset['Total_Value'].cummax()
                df_asset['Drawdown'] = (df_asset['Total_Value'] / df_asset['HWM'] - 1) * 100
                mdd = df_asset['Drawdown'].min()
                
                show_volatility = st.toggle("🚨 주요 하락장/고변동성 구간 차트에 음영 표시 (MDD -10% 기준)")
                
                fig = go.Figure()
                # 원금(누적 투자금) 추세선 추가
                fig.add_trace(go.Scatter(
                    x=df_asset.index, 
                    y=df_asset['Total_Invested'], 
                    mode='lines', 
                    name='누적 투자 원금', 
                    line=dict(color='rgba(150, 150, 150, 0.6)', width=2, dash='dash')
                ))
                # 퀀트 전략 자산 추세선
                fig.add_trace(go.Scatter(
                    x=df_asset.index, 
                    y=df_asset['Total_Value'], 
                    mode='lines', 
                    name='나의 퀀트 랩 자산', 
                    line=dict(color='#00CC96', width=3)
                ))
                
                if show_volatility:
                    is_dd = df_asset['Drawdown'] <= -10.0
                    dd_starts = df_asset.index[is_dd & ~is_dd.shift(1).fillna(False)]
                    dd_ends = df_asset.index[is_dd & ~is_dd.shift(-1).fillna(False)]
                    for s, e in zip(dd_starts, dd_ends):
                        fig.add_vrect(
                            x0=s, x1=e, fillcolor="rgba(255, 75, 75, 0.15)", layer="below", line_width=0,
                            annotation_text="고변동성", annotation_position="top left", annotation_font_size=10, annotation_font_color="red"
                        )
                
                fig.update_layout(height=400, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified")
                st.plotly_chart(fig, width="stretch")
                
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("최종 자산 (만원)", f"{final_val/10000:,.0f}")
                rc2.metric("CAGR (%)", f"{cagr:.2f}%")
                rc3.metric("MDD (%)", f"{mdd:.2f}%")

                with st.expander("🔍 포트폴리오 편입 종목 상세 수익률 분석", expanded=False):
                    ticker_to_name = dict(zip(df_all['ticker'], df_all['종목명']))
                    stock_returns = {}
                    final_prices = price_pivot.loc[available_dates[-1]]
                    
                    for t, buy_p in first_buy_price.items():
                        if buy_p > 0:
                            final_p = final_prices.get(t, 0)
                            if final_p > 0:
                                ret = (final_p / buy_p - 1) * 100
                                name = ticker_to_name.get(t, t)
                                stock_returns[name] = ret
                                
                    if stock_returns:
                        # 수익률 기준 오름차순 정렬 (Plotly의 가로 막대 차트는 아래부터 위로 렌더링되므로 오름차순이 시각적으로 내림차순처럼 보임)
                        df_stock_ret = pd.DataFrame(list(stock_returns.items()), columns=['종목명', '수익률']).sort_values('수익률', ascending=True)
                        colors = ['#00CC96' if val >= 0 else '#FF4B4B' for val in df_stock_ret['수익률']]
                        
                        fig_bar = go.Figure(go.Bar(
                            x=df_stock_ret['수익률'],
                            y=df_stock_ret['종목명'],
                            orientation='h',
                            marker_color=colors,
                            text=df_stock_ret['수익률'].apply(lambda x: f"{x:.1f}%"),
                            textposition='outside'
                        ))
                        fig_bar.update_layout(
                            height=max(400, len(df_stock_ret) * 25), # 종목이 많아지면 차트 높이 자동 확장
                            margin=dict(l=20, r=40, t=30, b=20),
                            xaxis_title="누적 수익률 (%)",
                            yaxis_title="",
                        )
                        st.plotly_chart(fig_bar, width="stretch")
                    else:
                        st.info("편입된 종목이 없습니다.")

                with st.expander("📉 구간별 낙폭(Drawdown) 심층 분석", expanded=False):
                    fig_dd = go.Figure()
                    fig_dd.add_trace(go.Scatter(x=df_asset.index, y=df_asset['Drawdown'], fill='tozeroy', mode='lines', name='Drawdown', line=dict(color='#FF4B4B', width=2)))
                    fig_dd.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified", yaxis_title="낙폭 (%)")
                    st.plotly_chart(fig_dd, width="stretch")
                    st.caption("✔️ 차트의 깊은 붉은 영역이 시스템이 수학적으로 찾아낸 계좌의 최대 스트레스(Drawdown) 구간입니다.")