import streamlit as st
import os
import json
import sqlite3
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
from dotenv import load_dotenv

# 환경변수 로드
load_dotenv()
TURSO_DB_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

PORTFOLIO_LOCK_PATH = os.path.abspath("./data_cache/portfolio_lock.json")

# ==========================================
# 1. 초기 UI 및 Session State(메모리) 설정
# ==========================================
st.set_page_config(page_title="초고속 퀀트 대시보드", layout="wide")

# --- 제품 #4: 회원 (우측 상단 콤팩트) ---
from auth_users import authenticate, register_user, user_from_session, ensure_users_table

# ---------------------------------------------------------------------------
# BETA: 회원 전용 게이트 임시 해제 (포트 확정·보고서 다운로드)
# 정식/유료화 전에 반드시 False 로 되돌릴 것. (.env BETA_SKIP_AUTH_GATES=0)
# 로드맵: product-roadmap-ux.mdc → 「베타: 인증 게이트 복구」
# ---------------------------------------------------------------------------
_BETA_SKIP_AUTH_GATES = os.getenv("BETA_SKIP_AUTH_GATES", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

ensure_users_table()
if "auth_user" not in st.session_state:
    st.session_state.auth_user = None
_auth = user_from_session(st.session_state.auth_user)
_IS_LOGGED_IN = _auth is not None
# 베타에서는 로그인 없이도 확정/다운로드 허용. 정식 출시 시 _BETA_SKIP_AUTH_GATES=False
_CAN_USE_MEMBER_FEATURES = _IS_LOGGED_IN or _BETA_SKIP_AUTH_GATES

st.markdown(
    """
<style>
/* 헤더 우측 회원 버튼 콤팩트 */
div[data-testid="stPopover"] > button {
  font-size: 0.85rem !important;
  padding: 0.25rem 0.7rem !important;
  min-height: 2rem !important;
  white-space: nowrap;
}
</style>
""",
    unsafe_allow_html=True,
)

_hdr_l, _hdr_r = st.columns([5.5, 1.15])
with _hdr_l:
    st.title("🧪 다이내믹 퀀트 랩 V2 (실전 백테스트 엔진)")
    if _BETA_SKIP_AUTH_GATES:
        st.caption(
            "SQLite 고속 DB 기반 | 점진적 공개 UI | "
            "**베타: 로그인 없이 포트 확정·보고서 다운로드 가능** (정식 전 인증 복구 예정)"
        )
    else:
        st.caption("SQLite 고속 DB 기반 | 점진적 공개(Progressive Disclosure) UI 적용")
with _hdr_r:
    st.write("")  # 타이틀과 대략 맞춤
    if _auth:
        _label = f"👤 {_auth.get('display_name') or '회원'}"
        with st.popover(_label, use_container_width=True):
            st.caption(f"{_auth.get('email', '')}")
            st.caption(f"플랜 · {_auth.get('tier', 'free')}")
            if st.button("로그아웃", key="btn_logout", use_container_width=True):
                st.session_state.auth_user = None
                st.rerun()
    else:
        with st.popover("👤 로그인 / 가입", use_container_width=True):
            _tab_login, _tab_reg = st.tabs(["로그인", "가입"])
            with _tab_login:
                _le = st.text_input("이메일", key="login_email")
                _lp = st.text_input("비밀번호", type="password", key="login_pw")
                if st.button("로그인", key="btn_login", use_container_width=True):
                    ok, msg, user = authenticate(_le, _lp)
                    if ok and user:
                        st.session_state.auth_user = user
                        st.rerun()
                    else:
                        st.error(msg)
            with _tab_reg:
                _re = st.text_input("이메일", key="reg_email")
                _rn = st.text_input("닉네임", key="reg_name", placeholder="선택")
                _rp = st.text_input("비밀번호 (8자+)", type="password", key="reg_pw")
                _rp2 = st.text_input("비밀번호 확인", type="password", key="reg_pw2")
                if st.button("가입하기", key="btn_reg", use_container_width=True):
                    if _rp != _rp2:
                        st.error("비밀번호 확인이 일치하지 않습니다.")
                    else:
                        ok, msg, user = register_user(_re, _rp, _rn)
                        if ok and user:
                            st.session_state.auth_user = user
                            st.rerun()
                        else:
                            st.error(msg)
            if _BETA_SKIP_AUTH_GATES:
                st.caption("베타: 로그인 없이도 포트 확정·다운로드 가능")
            else:
                st.caption("로그인 시 포트 확정·보고서 다운로드 가능")

# --- 메뉴: 퀀트 랩 / 사용 안내 ---
_nav = st.sidebar.radio(
    "메뉴",
    ["🧪 퀀트 랩", "📖 사용 안내"],
    index=0,
    key="app_nav",
    help="사용 안내: 투자 룰·백테스트 해석·CAGR/MDD 등 용어 설명",
)
if _nav == "📖 사용 안내":
    from user_guide import render_user_guide

    render_user_guide()
    st.stop()

# 직전 AI 매크로 비중 캐시(재시작/새로고침 후에도 유지)
try:
    from macro_ai_agent import (
        load_ai_weights as _load_ai_macro_weights,
        DEFAULT_SUB_VALUE as _DEF_SV,
        DEFAULT_SUB_QUALITY as _DEF_SQ,
        DEFAULT_SUB_MOMENTUM as _DEF_SM,
    )
    _cached_macro = _load_ai_macro_weights()
except Exception:
    _cached_macro = None
    _DEF_SV = {"per": 25, "pbr": 25, "psr": 15, "ev": 15, "per_sec": 10, "pbr_sec": 10}
    _DEF_SQ = {
        "roe": 12,
        "opm": 7,
        "gpm": 7,
        "fscore": 7,
        "vol": 10,
        "accrual": 9,
        "fcf": 9,
        "growth": 10,
        "div": 9,
        "share": 8,
        "treasury": 12,
    }

    _DEF_SM = {"price": 40, "earn": 35, "factor": 25, "mom1": 20, "mom6": 40, "mom12": 40}

def _ai_sub(group: str, key: str, default: int) -> int:
    if not _cached_macro:
        return default
    block = _cached_macro.get(group) or {}
    try:
        return int(block.get(key, default))
    except (TypeError, ValueError):
        return default

if 'step1_unlocked' not in st.session_state:
    st.session_state.step1_unlocked = False
if 'step2_unlocked' not in st.session_state:
    st.session_state.step2_unlocked = False
if 'w_val' not in st.session_state:
    st.session_state.w_val = int(_cached_macro['value']) if _cached_macro else 40
if 'w_qual' not in st.session_state:
    st.session_state.w_qual = int(_cached_macro['quality']) if _cached_macro else 40
if 'w_mom' not in st.session_state:
    st.session_state.w_mom = int(_cached_macro['momentum']) if _cached_macro else 20
if 'ai_reason' not in st.session_state:
    st.session_state.ai_reason = (_cached_macro.get('reason') if _cached_macro else "") or ""

# 세부 슬라이더 세션 키 (AI가 덮어쓸 수 있도록 key 고정)
_SUB_DEFAULTS = {
    "sub_per": _ai_sub("sub_value", "per", _DEF_SV["per"]),
    "sub_pbr": _ai_sub("sub_value", "pbr", _DEF_SV["pbr"]),
    "sub_psr": _ai_sub("sub_value", "psr", _DEF_SV["psr"]),
    "sub_ev": _ai_sub("sub_value", "ev", _DEF_SV["ev"]),
    "sub_per_sec": _ai_sub("sub_value", "per_sec", _DEF_SV.get("per_sec", 10)),
    "sub_pbr_sec": _ai_sub("sub_value", "pbr_sec", _DEF_SV.get("pbr_sec", 10)),
    "sub_roe": _ai_sub("sub_quality", "roe", _DEF_SQ["roe"]),
    "sub_opm": _ai_sub("sub_quality", "opm", _DEF_SQ["opm"]),
    "sub_gpm": _ai_sub("sub_quality", "gpm", _DEF_SQ["gpm"]),
    "sub_fscore": _ai_sub("sub_quality", "fscore", _DEF_SQ["fscore"]),
    "sub_vol": _ai_sub("sub_quality", "vol", _DEF_SQ.get("vol", 16)),
    "sub_accrual": _ai_sub("sub_quality", "accrual", _DEF_SQ.get("accrual", 13)),
    "sub_fcf": _ai_sub("sub_quality", "fcf", _DEF_SQ.get("fcf", 10)),
    "sub_growth": _ai_sub("sub_quality", "growth", _DEF_SQ.get("growth", 12)),
    "sub_div": _ai_sub("sub_quality", "div", _DEF_SQ.get("div", 9)),
    "sub_share": _ai_sub("sub_quality", "share", _DEF_SQ.get("share", 8)),
    "sub_treasury": _ai_sub("sub_quality", "treasury", _DEF_SQ.get("treasury", 12)),
    "sub_price_mom": _ai_sub("sub_momentum", "price", _DEF_SM["price"]),
    "sub_earn_mom": _ai_sub("sub_momentum", "earn", _DEF_SM["earn"]),
    "sub_factor_mom": _ai_sub("sub_momentum", "factor", _DEF_SM["factor"]),
    "sub_mom1": _ai_sub("sub_momentum", "mom1", _DEF_SM["mom1"]),
    "sub_mom6": _ai_sub("sub_momentum", "mom6", _DEF_SM["mom6"]),
    "sub_mom12": _ai_sub("sub_momentum", "mom12", _DEF_SM["mom12"]),
}
for _k, _v in _SUB_DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

def reset_ui_state():
    """하위 단계 unlock만 리셋. 매크로/세부 비중·ai_reason은 절대 건드리지 않음."""
    st.session_state.step1_unlocked = False
    st.session_state.step2_unlocked = False


def reset_backtest_only():
    """투자 룰·버퍼만 바꿀 때: 랭킹 표는 유지, 백테스트만 다시 돌리게 함."""
    st.session_state.step2_unlocked = False

def apply_ai_weights_to_session(ai_weights: dict):
    st.session_state.w_val = int(ai_weights.get("value", 34))
    st.session_state.w_qual = int(ai_weights.get("quality", 33))
    st.session_state.w_mom = int(ai_weights.get("momentum", 33))
    st.session_state.ai_reason = str(ai_weights.get("reason") or "").strip()
    sv = ai_weights.get("sub_value") or {}
    sq = ai_weights.get("sub_quality") or {}
    sm = ai_weights.get("sub_momentum") or {}
    st.session_state.sub_per = int(sv.get("per", 25))
    st.session_state.sub_pbr = int(sv.get("pbr", 25))
    st.session_state.sub_psr = int(sv.get("psr", 15))
    st.session_state.sub_ev = int(sv.get("ev", 15))
    st.session_state.sub_per_sec = int(sv.get("per_sec", 10))
    st.session_state.sub_pbr_sec = int(sv.get("pbr_sec", 10))
    st.session_state.sub_roe = int(sq.get("roe", 30))
    st.session_state.sub_opm = int(sq.get("opm", 15))
    st.session_state.sub_gpm = int(sq.get("gpm", 15))
    st.session_state.sub_fscore = int(sq.get("fscore", 15))
    st.session_state.sub_vol = int(sq.get("vol", 16))
    st.session_state.sub_accrual = int(sq.get("accrual", 13))
    st.session_state.sub_fcf = int(sq.get("fcf", 10))
    st.session_state.sub_growth = int(sq.get("growth", 12))
    st.session_state.sub_div = int(sq.get("div", 9))
    st.session_state.sub_share = int(sq.get("share", 8))
    st.session_state.sub_treasury = int(sq.get("treasury", 12))
    st.session_state.sub_price_mom = int(sm.get("price", 40))
    st.session_state.sub_earn_mom = int(sm.get("earn", 35))
    st.session_state.sub_factor_mom = int(sm.get("factor", 25))
    st.session_state.sub_mom1 = int(sm.get("mom1", 20))
    st.session_state.sub_mom6 = int(sm.get("mom6", 40))
    st.session_state.sub_mom12 = int(sm.get("mom12", 40))

# ==========================================
# 2. 초고속 DB 로드 (캐시 만료 시간 1시간 설정)
# ==========================================
@st.cache_data(ttl=3600)
def load_db_data():
    conn = sqlite3.connect('data_cache/quant_history.db')
    # 스키마 보장
    try:
        from factor_builder import ensure_factor_columns
        ensure_factor_columns(conn)
        conn.commit()
    except Exception:
        pass

    cols = {r[1] for r in conn.execute("PRAGMA table_info(monthly_factor)")}
    earn_sel = "f.earn_mom" if "earn_mom" in cols else "NULL AS earn_mom"
    fm_sel = "f.factor_mom" if "factor_mom" in cols else "NULL AS factor_mom"
    acc_sel = "f.accrual" if "accrual" in cols else "NULL AS accrual"
    fcf_sel = "f.fcf_yield" if "fcf_yield" in cols else "NULL AS fcf_yield"
    g_sel = "f.growth_stab" if "growth_stab" in cols else "NULL AS growth_stab"
    div_sel = "f.div_yield" if "div_yield" in cols else "NULL AS div_yield"
    sh_sel = "f.share_growth" if "share_growth" in cols else "NULL AS share_growth"
    ts_sel = "f.treasury_chg" if "treasury_chg" in cols else "NULL AS treasury_chg"
    s1 = "f.sales_g1y" if "sales_g1y" in cols else "NULL AS sales_g1y"
    o1 = "f.op_g1y" if "op_g1y" in cols else "NULL AS op_g1y"
    n1 = "f.ni_g1y" if "ni_g1y" in cols else "NULL AS ni_g1y"
    es = "f.earn_surprise" if "earn_surprise" in cols else "NULL AS earn_surprise"
    query_factor = f"""
        SELECT f.date, f.ticker, m.name as '종목명', m.sector as '섹터', 
               f.per, f.pbr, f.psr, f.ev_ebitda, f.roe, f.op_margin, f.gross_margin, 
               f.f_score, f.mom_1m, f.mom_6m, f.mom_12m, {earn_sel}, {fm_sel},
               {acc_sel}, {fcf_sel}, {g_sel}, {div_sel}, {sh_sel}, {ts_sel},
               {s1}, {o1}, {n1}, {es}
        FROM monthly_factor f
        JOIN stock_master m ON f.ticker = m.ticker
        WHERE m.is_active = 1
    """
    df_factor = pd.read_sql(query_factor, conn)

    # ETL로 들어온 헤더 잔여행/문자열 혼재를 숫자형으로 강제 정규화
    factor_cols = [
        'per', 'pbr', 'psr', 'ev_ebitda', 'roe', 'op_margin', 'gross_margin',
        'f_score', 'mom_1m', 'mom_6m', 'mom_12m', 'earn_mom', 'factor_mom',
        'accrual', 'fcf_yield', 'growth_stab', 'div_yield', 'share_growth', 'treasury_chg',
        'sales_g1y', 'op_g1y', 'ni_g1y', 'earn_surprise',
    ]
    for col in factor_cols:
        if col in df_factor.columns:
            df_factor[col] = pd.to_numeric(df_factor[col], errors='coerce')

    # 가치 멀티플: 0 이하는 결측 처리 (낮을수록 좋음 랭크에서 0=1등 버그 방지)
    for col in ("per", "pbr", "psr", "ev_ebitda"):
        if col in df_factor.columns:
            df_factor.loc[df_factor[col] <= 0, col] = np.nan

    # 모멘텀 이상치: -100% 고정값·전구간 0 은 데이터 결함으로 간주
    for col in ("mom_1m", "mom_6m", "mom_12m"):
        if col in df_factor.columns:
            df_factor.loc[df_factor[col] <= -99.9, col] = np.nan
    if {"mom_1m", "mom_6m", "mom_12m"}.issubset(df_factor.columns):
        all_zero = (
            (df_factor["mom_1m"].fillna(0) == 0)
            & (df_factor["mom_6m"].fillna(0) == 0)
            & (df_factor["mom_12m"].isna() | (df_factor["mom_12m"].fillna(0) == 0))
        )
        # per/pbr/psr도 전부 결측인 행의 0 모멘텀은 신뢰하지 않음
        val_missing = (
            df_factor["per"].isna() & df_factor["pbr"].isna() & df_factor["psr"].isna()
        )
        bad_mom = all_zero & val_missing
        for col in ("mom_1m", "mom_6m", "mom_12m"):
            df_factor.loc[bad_mom, col] = np.nan

    # 티커 표준화: '005930' / 'A005930' → 'A005930' (daily_price와 조인 정합)
    def _norm_ticker(x):
        s = str(x).strip()
        if s.upper().startswith('A') and len(s) >= 7:
            return 'A' + ''.join(ch for ch in s[1:] if ch.isdigit()).zfill(6)[-6:]
        digits = ''.join(ch for ch in s if ch.isdigit()).zfill(6)[-6:]
        return f'A{digits}' if digits != '000000' else s

    df_factor['ticker'] = df_factor['ticker'].map(_norm_ticker)
    df_factor = df_factor[df_factor['ticker'].astype(str).str.match(r'^A\d{6}$', na=False)].copy()

    # factor_mom: DB 값이 충분하면 재계산 생략(캐시/속도). 부족하면 런타임 산출
    need_fm = (
        "factor_mom" not in df_factor.columns
        or df_factor["factor_mom"].notna().mean() < 0.5
    )
    if need_fm:
        try:
            from momentum_engine import attach_factor_momentum
            df_factor = attach_factor_momentum(df_factor, lookback=6)
        except Exception as e:
            if "factor_mom" not in df_factor.columns:
                df_factor["factor_mom"] = np.nan
            print(f"[warn] factor_mom 산출 실패: {e}")
    
    query_price = "SELECT date, ticker, close, volume FROM daily_price"
    try:
        df_price = pd.read_sql(query_price, conn)
        if not df_price.empty:
            df_price['date'] = pd.to_datetime(df_price['date'])
            df_price['close'] = pd.to_numeric(df_price['close'], errors='coerce')
            if "volume" in df_price.columns:
                df_price["volume"] = pd.to_numeric(df_price["volume"], errors="coerce")
            df_price["ticker"] = df_price["ticker"].map(_norm_ticker)
            # '005930'+'A005930' 정규화 충돌 → pivot 시 duplicate index 방지
            df_price = df_price.drop_duplicates(subset=["date", "ticker"], keep="last")
            # 유니버스에 있는 종목만 남겨 피벗 메모리/속도 최적화
            universe = set(df_factor['ticker'].unique())
            df_price = df_price[df_price['ticker'].isin(universe)].dropna(subset=['close'])
        else:
            df_price = pd.DataFrame()
    except Exception:
        # volume 컬럼 없는 구 DB 호환
        try:
            df_price = pd.read_sql("SELECT date, ticker, close FROM daily_price", conn)
            if not df_price.empty:
                df_price["date"] = pd.to_datetime(df_price["date"])
                df_price["close"] = pd.to_numeric(df_price["close"], errors="coerce")
                df_price["volume"] = np.nan
                df_price["ticker"] = df_price["ticker"].map(_norm_ticker)
                df_price = df_price.drop_duplicates(subset=["date", "ticker"], keep="last")
                universe = set(df_factor["ticker"].unique())
                df_price = df_price[df_price["ticker"].isin(universe)].dropna(subset=["close"])
            else:
                df_price = pd.DataFrame()
        except Exception:
            df_price = pd.DataFrame()

    # Phase A1–A2: 저변동 + 섹터 상대 가치
    try:
        from factor_extras import attach_sector_relative, attach_vol_12m
        df_factor = attach_sector_relative(df_factor)
        df_factor = attach_vol_12m(df_factor, df_price)
    except Exception as e:
        df_factor["per_sec"] = np.nan
        df_factor["pbr_sec"] = np.nan
        df_factor["vol_12m"] = np.nan
        print(f"[warn] Phase A extras 실패: {e}")
        
    conn.close()
    return df_factor, df_price

df_all, df_price_all = load_db_data()

if df_all.empty:
    st.error("❌ DB 데이터가 없습니다. 터미널에서 'python quant_etl.py'를 먼저 실행해 주세요.")
    st.stop()

latest_date = df_all['date'].max()
factor_start = df_all['date'].min()
df_main = df_all[df_all['date'] == latest_date].copy()

# 팩터 커버리지 안내 (백테스트 기간과 불일치 시 가시성)
st.sidebar.caption(
    f"📦 팩터 데이터 구간: **{factor_start} ~ {latest_date}**",
    help="백테스트는 이 구간의 월별 팩터로만 리밸런싱됩니다. 그 이전은 현금/미편입 상태가 됩니다."
)

# ==========================================
# 3. 🎛️ 좌측 사이드바: 팩터 설계소
# ==========================================
try:
    db_mtime = os.path.getmtime('data_cache/quant_history.db')
    db_date = datetime.fromtimestamp(db_mtime).strftime('%Y-%m-%d')
except FileNotFoundError:
    db_date = "알 수 없음"

st.sidebar.caption(
    f"✅ DB 최종 갱신일: {db_date} (상세 보기 Hover)", 
    help="매월 1일 GitHub Actions를 통해 최신 공시 및 주가 데이터가 자동 동기화됩니다."
)
if st.sidebar.button("🔄 데이터 캐시 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("### 🎛️ 나만의 팩터 설계소")

if st.sidebar.button("🤖 AI 매크로 비중 자동 할당", type="primary", use_container_width=True):
    with st.spinner("Perplexity로 뉴스·공시·시황 분석 중... (약 10~20초)"):
        import importlib
        import macro_ai_agent
        importlib.reload(macro_ai_agent)
        ai_weights = macro_ai_agent.get_monthly_factor_weights(force_refresh=True)
        apply_ai_weights_to_session(ai_weights)
        st.session_state.pending_monthly_report = True
        st.session_state._report_weights = ai_weights
        reset_ui_state()
        st.rerun()

if st.sidebar.button("📄 이달의 AI 보고서 다시 보기", use_container_width=True):
    from monthly_report import load_saved_report
    saved = load_saved_report()
    if saved:
        st.session_state.monthly_report_md = saved
        st.session_state.show_monthly_report = True
    else:
        st.sidebar.warning("저장된 보고서가 없습니다. 먼저 AI 매크로를 실행하세요.")

w_value = st.sidebar.slider(
    "가치 (Value)", 0, 100, key='w_val', on_change=reset_ui_state,
    help="싸게 평가된 종목 비중. 높일수록 PER·PBR 등 저평가 신호가 강한 종목을 우대합니다.",
)
w_quality = st.sidebar.slider(
    "우량 (Quality)", 0, 100, key='w_qual', on_change=reset_ui_state,
    help="재무 품질·수익성 비중. 높일수록 ROE·마진·현금흐름·저변동 등 우량 신호가 강한 종목을 우대합니다.",
)
w_momentum = st.sidebar.slider(
    "모멘텀 (Momentum)", 0, 100, key='w_mom', on_change=reset_ui_state,
    help="추세·실적 모멘텀 비중. 높일수록 최근 주가·이익이 잘 오른 종목을 우대합니다.",
)

if st.session_state.ai_reason:
    st.sidebar.success("💡 AI 매크로 비중 근거 (Perplexity)")
    st.sidebar.caption(st.session_state.ai_reason)

total_macro = w_value + w_quality + w_momentum
if total_macro > 0:
    real_w_val, real_w_qual, real_w_mom = w_value / total_macro, w_quality / total_macro, w_momentum / total_macro
else:
    real_w_val = real_w_qual = real_w_mom = 0

with st.sidebar.expander("🔽 가치(Value) 세부 비중", expanded=False):
    sub_per = st.slider(
        "PER (순이익)", 0, 100, key="sub_per", on_change=reset_ui_state,
        help="주가/순이익. 낮을수록 이익 대비 저평가. 슬라이더↑ = 저PER 종목 더 우대.",
    )
    sub_pbr = st.slider(
        "PBR (순자산)", 0, 100, key="sub_pbr", on_change=reset_ui_state,
        help="주가/순자산. 낮을수록 자산 대비 저평가. 슬라이더↑ = 저PBR 우대.",
    )
    sub_psr = st.slider(
        "PSR (매출액)", 0, 100, key="sub_psr", on_change=reset_ui_state,
        help="주가/매출. 낮을수록 매출 대비 저평가. 슬라이더↑ = 저PSR 우대.",
    )
    sub_ev = st.slider(
        "EV/EBITDA", 0, 100, key="sub_ev", on_change=reset_ui_state,
        help="기업가치/영업현금창출력. 낮을수록 저평가. 슬라이더↑ = 낮은 EV/EBITDA 우대.",
    )
    sub_per_sec = st.slider(
        "PER 섹터상대 (z)", 0, 100, key="sub_per_sec", on_change=reset_ui_state,
        help="같은 섹터 대비 PER z-score. 낮을수록 업종 내 상대 저평가. 슬라이더↑ = 섹터 대비 싼 종목 우대.",
    )
    sub_pbr_sec = st.slider(
        "PBR 섹터상대 (z)", 0, 100, key="sub_pbr_sec", on_change=reset_ui_state,
        help="같은 섹터 대비 PBR z-score. 낮을수록 업종 내 상대 저평가. 슬라이더↑ = 섹터 대비 싼 종목 우대.",
    )
    
    tot_val_sub = sub_per + sub_pbr + sub_psr + sub_ev + sub_per_sec + sub_pbr_sec
    f_per, f_pbr, f_psr, f_ev, f_per_sec, f_pbr_sec = [
        x / tot_val_sub * real_w_val if tot_val_sub > 0 else 0
        for x in (sub_per, sub_pbr, sub_psr, sub_ev, sub_per_sec, sub_pbr_sec)
    ]

with st.sidebar.expander("🔽 우량(Quality) 세부 비중", expanded=False):
    sub_roe = st.slider(
        "ROE (자본수익률)", 0, 100, key="sub_roe", on_change=reset_ui_state,
        help="순이익/자기자본. 높을수록 자본 효율↑. 슬라이더↑ = 고ROE 우대.",
    )
    sub_opm = st.slider(
        "OPM (영업이익률)", 0, 100, key="sub_opm", on_change=reset_ui_state,
        help="영업이익/매출. 높을수록 본업 수익성↑. 슬라이더↑ = 고마진 우대.",
    )
    sub_gpm = st.slider(
        "GPM (매출총이익률)", 0, 100, key="sub_gpm", on_change=reset_ui_state,
        help="매출총이익/매출. 높을수록 제품·원가 우위. 슬라이더↑ = 고GPM 우대.",
    )
    sub_fscore = st.slider(
        "F-Score (재무건전성)", 0, 100, key="sub_fscore", on_change=reset_ui_state,
        help="Piotroski식 0~9 정수(신호 합). 높을수록 재무 개선·건전. 슬라이더↑ = 고F-Score 우대.",
    )
    sub_vol = st.slider(
        "저변동 vol_12m (낮을수록↑)", 0, 100, key="sub_vol", on_change=reset_ui_state,
        help="12개월 연율 변동성. 낮을수록 주가 흔들림↓(방어). 슬라이더↑ = 저변동 종목 우대.",
    )
    sub_accrual = st.slider(
        "Accrual (NI-CFO)/Assets 낮을수록↑", 0, 100, key="sub_accrual", on_change=reset_ui_state,
        help="발생액 비중. 낮을수록 이익이 현금과 잘 맞음(품질↑). 슬라이더↑ = 저Accrual 우대.",
    )
    sub_fcf = st.slider(
        "FCF Yield (높을수록↑)", 0, 100, key="sub_fcf", on_change=reset_ui_state,
        help="잉여현금흐름/시총. 높을수록 현금창출력 대비 저평가. 슬라이더↑ = 고FCF Yield 우대.",
    )
    sub_growth = st.slider(
        "다년성장 growth_stab (높을수록↑)", 0, 100, key="sub_growth", on_change=reset_ui_state,
        help="3년 매출·영업·순이익 성장의 안정 점수. 높을수록 꾸준한 성장. 슬라이더↑ = 고성장안정 우대.",
    )
    sub_div = st.slider(
        "배당수익률 div_yield (높을수록↑)", 0, 100, key="sub_div", on_change=reset_ui_state,
        help="연간배당/주가. 높을수록 배당 매력↑. 슬라이더↑ = 고배당 우대.",
    )
    sub_share = st.slider(
        "주식수증가 share_growth (낮을수록↑)", 0, 100, key="sub_share", on_change=reset_ui_state,
        help="주식수 증가율(희석). 낮을수록(음수=자사주·감자) 주주 유리. 슬라이더↑ = 저희석 우대.",
    )
    sub_treasury = st.slider(
        "자사주비중증가 treasury_chg (높을수록↑)", 0, 100, key="sub_treasury", on_change=reset_ui_state,
        help="자사주 비중 YoY 증가. 높을수록 자사주 매입·소각 성향. 슬라이더↑ = 자사주 증가 우대.",
    )
    
    tot_qual_sub = (
        sub_roe + sub_opm + sub_gpm + sub_fscore + sub_vol
        + sub_accrual + sub_fcf + sub_growth + sub_div + sub_share + sub_treasury
    )
    f_roe, f_opm, f_gpm, f_fscore, f_vol, f_accrual, f_fcf, f_growth, f_div, f_share, f_treasury = [
        x / tot_qual_sub * real_w_qual if tot_qual_sub > 0 else 0
        for x in (
            sub_roe, sub_opm, sub_gpm, sub_fscore, sub_vol,
            sub_accrual, sub_fcf, sub_growth, sub_div, sub_share, sub_treasury,
        )
    ]

with st.sidebar.expander("🔽 모멘텀(Momentum) 세부 비중", expanded=False):
    st.caption("3축: 가격 · 이익 · 팩터 모멘텀")
    sub_price_mom = st.slider(
        "가격 모멘텀 (Price)", 0, 100, key="sub_price_mom", on_change=reset_ui_state,
        help="주가 추세 모멘텀 축 비중. 슬라이더↑ = 최근 상승 종목 더 우대.",
    )
    sub_earn_mom = st.slider(
        "이익 모멘텀 (Earnings)", 0, 100, key="sub_earn_mom", on_change=reset_ui_state,
        help="영업·순이익 YoY 등 실적 모멘텀. 높을수록 실적 개선. 슬라이더↑ = 고이익모멘텀 우대.",
    )
    sub_factor_mom = st.slider(
        "팩터 모멘텀 (Factor)", 0, 100, key="sub_factor_mom", on_change=reset_ui_state,
        help="최근 잘 먹힌 스타일(가치·우량·가격)에 대한 종목 노출. 슬라이더↑ = 팩터모멘텀 우대.",
    )
    tot_mom_pillar = sub_price_mom + sub_earn_mom + sub_factor_mom
    w_price_p, w_earn_p, w_factor_p = [
        x / tot_mom_pillar * real_w_mom if tot_mom_pillar > 0 else 0
        for x in (sub_price_mom, sub_earn_mom, sub_factor_mom)
    ]

    st.caption("가격 모멘텀 Horizon")
    sub_mom1 = st.slider(
        "1개월 등락률", 0, 100, key="sub_mom1", on_change=reset_ui_state,
        help="최근 1개월 주가 수익률. 높을수록 단기 강세. 슬라이더↑ = 단기 모멘텀 우대.",
    )
    sub_mom6 = st.slider(
        "6개월 등락률", 0, 100, key="sub_mom6", on_change=reset_ui_state,
        help="최근 6개월 주가 수익률. 중기 추세. 슬라이더↑ = 6개월 모멘텀 우대.",
    )
    sub_mom12 = st.slider(
        "12개월 등락률", 0, 100, key="sub_mom12", on_change=reset_ui_state,
        help="최근 12개월 주가 수익률. 장기 추세. 슬라이더↑ = 12개월 모멘텀 우대.",
    )
    tot_mom_hz = sub_mom1 + sub_mom6 + sub_mom12
    f_mom1, f_mom6, f_mom12 = [
        x / tot_mom_hz * w_price_p if tot_mom_hz > 0 else 0
        for x in (sub_mom1, sub_mom6, sub_mom12)
    ]
    f_earn_mom = w_earn_p
    f_factor_mom = w_factor_p

# --- 제품 #1: 유동성(거래대금) 필터 (절대컷 + 하위% + 시총) ---
st.sidebar.markdown("### 💧 유동성 필터")
liq_filter_on = st.sidebar.checkbox(
    "유동성 필터 사용",
    value=False,
    key="liq_filter_on",
    help="20일 평균 거래대금·(선택) 하위% 절사·시총 하위를 랭킹·백테스트에서 제외합니다.",
    on_change=reset_ui_state,
)
min_tv_eok = st.sidebar.slider(
    "최소 평균 거래대금 (억 원)",
    min_value=1,
    max_value=50,
    value=10,
    step=1,
    key="min_tv_eok",
    disabled=not liq_filter_on,
    help="권장 안전선 10억. 보수적 전략은 30~50억.",
    on_change=reset_ui_state,
)
# 점진적 공개: 상대·시총 컷
liq_adv = False
tv_bottom_pct = 0.0
marcap_bottom_pct = 0.0
if liq_filter_on:
    liq_adv = st.sidebar.checkbox(
        "고급: 하위% · 시총 필터",
        value=False,
        key="liq_adv_on",
        help="시장 전체 대비 상대 절사 + 시총 꼬리 제거(테마 동전주 방어).",
        on_change=reset_ui_state,
    )
if liq_filter_on and liq_adv:
    tv_bottom_pct = (
        st.sidebar.slider(
            "거래대금 하위 절사 (%)",
            min_value=0,
            max_value=30,
            value=20,
            step=5,
            key="liq_tv_bottom_pct",
            help="0=끄기. 20이면 20일 평균 거래대금 하위 20% 제외.",
            on_change=reset_ui_state,
        )
        / 100.0
    )
    marcap_bottom_pct = (
        st.sidebar.slider(
            "시총 하위 절사 (%)",
            min_value=0,
            max_value=20,
            value=10,
            step=5,
            key="liq_marcap_bottom_pct",
            help="0=끄기. monthly_shares가 없으면 현재 상장 시총(FDR) 근사.",
            on_change=reset_ui_state,
        )
        / 100.0
    )
MIN_TV_WON = float(min_tv_eok) * 1e8
_LIQ_MARCAP_MAP: dict = {}
_LIQ_MARCAP_SRC = ""
if liq_filter_on and marcap_bottom_pct > 0:
    try:
        from liquidity_benchmark import load_marcap_map

        _dbp = os.path.abspath("./data_cache/quant_history.db")
        _LIQ_MARCAP_MAP = load_marcap_map(_dbp, asof_month=None, use_fdr_fallback=True)
        _has_ms = False
        try:
            _c = sqlite3.connect(_dbp, timeout=10)
            _has_ms = (
                _c.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='monthly_shares' LIMIT 1"
                ).fetchone()
                is not None
            )
            _c.close()
        except Exception:
            pass
        _LIQ_MARCAP_SRC = "PIT(monthly_shares)" if _has_ms else "현재시총(FDR)"
    except Exception:
        _LIQ_MARCAP_MAP = {}
        _LIQ_MARCAP_SRC = ""

# --- 투자 룰 · 리밸런싱 주기 (버퍼 / 캡 / 월·분기·반기) ---
from rebalance_rules import (
    BUFFER_PRESETS,
    REBALANCE_FREQ,
    TradeRules,
    resolve_buffer_preset,
)

st.sidebar.markdown("### 📐 투자 룰 · 리밸런싱")
_buf_labels = list(BUFFER_PRESETS.keys())
_buf_preset = st.sidebar.selectbox(
    "버퍼(순위) 프리셋",
    _buf_labels,
    index=0,
    key="buf_preset",
    help="매수 진입 순위와 유지(퇴출) 버퍼. 기관·스마트베타에서 쓰는 churning 완화 방식입니다.",
    on_change=reset_backtest_only,
)
_b_def, _h_def, _buf_help = BUFFER_PRESETS[_buf_preset]
st.sidebar.caption(_buf_help)
_buy_n = _b_def
_hold_n = _h_def
if _buf_preset == "커스텀":
    _buy_n = st.sidebar.number_input(
        "매수 진입 (상위 N위)",
        min_value=5,
        max_value=50,
        value=10,
        step=1,
        key="buf_buy_n",
        on_change=reset_backtest_only,
    )
    _hold_n = st.sidebar.number_input(
        "유지 상한 (M위)",
        min_value=int(_buy_n),
        max_value=80,
        value=max(20, int(_buy_n)),
        step=1,
        key="buf_hold_n",
        help="M위까지는 기존 보유 유지, M+1위부터 매도.",
        on_change=reset_backtest_only,
    )
_buy_n, _hold_n = resolve_buffer_preset(_buf_preset, int(_buy_n), int(_hold_n))

_cap_on = st.sidebar.checkbox(
    "단일 종목 비중 캡",
    value=True,
    key="stock_cap_on",
    help="유지 구간 종목이 상한을 넘으면 초과분만 매도(Trim). 쏠림·단일종목 리스크 완화.",
    on_change=reset_backtest_only,
)
_cap_pct = 15
if _cap_on:
    _cap_pct = st.sidebar.slider(
        "종목 최대 비중 (%)",
        min_value=5,
        max_value=30,
        value=15,
        step=1,
        key="stock_cap_pct",
        on_change=reset_backtest_only,
    )

_max_pos_on = st.sidebar.checkbox(
    "최대 보유 종목 수 제한",
    value=False,
    key="max_pos_on",
    help="한도에 도달하면 신규 편입만 막고, 기존 보유 종목의 유지·비중 맞추기·매도는 그대로 둡니다.",
    on_change=reset_backtest_only,
)
_max_positions = 0
if _max_pos_on:
    _max_positions = int(
        st.sidebar.number_input(
            "최대 보유 종목 수",
            min_value=5,
            max_value=40,
            value=min(40, max(5, int(_buy_n))),
            step=1,
            key="max_positions_n",
            help="예: 15 = 최대 15종목. 빈자리가 생길 때만 신규 매수.",
            on_change=reset_backtest_only,
        )
    )

_freq_labels = list(REBALANCE_FREQ.keys())
_freq_label = st.sidebar.selectbox(
    "리밸런싱 주기",
    _freq_labels,
    index=0,
    key="rebal_freq",
    help=(
        "월간: 반응↑·비용·MDD↑ / 분기: 실무 균형(샤프·비용) / "
        "반기: 저회전·가치·퀄리티에 유리. 적립금은 매월 투입, 매매만 주기 따름."
    ),
    on_change=reset_backtest_only,
)
_freq_months, _freq_help = REBALANCE_FREQ[_freq_label]
st.sidebar.caption(_freq_help)

# 기관식 확장 (점진적 공개)
_inst_on = st.sidebar.checkbox(
    "고급: 회전율·최소보유·ADV·섹터캡·MDD중단",
    value=False,
    key="inst_risk_on",
    help="시타델/스마트베타식 거래비용·리스크 제약. 체크 시에만 아래 한도 적용.",
    on_change=reset_backtest_only,
)
_turn_cap = 0.0
_min_hold = 0
_adv_pct = 0.0
_sec_cap = 0.0
_mdd_halt = 0.0
if _inst_on:
    _turn_on = st.sidebar.checkbox(
        "회전율 상한",
        value=True,
        key="turn_cap_on",
        help="1회 리밸런싱에서 매도+매수 명목합이 자산의 X%를 넘지 않게 비례 축소.",
        on_change=reset_backtest_only,
    )
    if _turn_on:
        _turn_cap = (
            st.sidebar.slider(
                "회전율 상한 (%)",
                min_value=5,
                max_value=50,
                value=20,
                step=5,
                key="turn_cap_pct",
                on_change=reset_backtest_only,
            )
            / 100.0
        )
    _hold_on = st.sidebar.checkbox(
        "최소 보유 주기",
        value=False,
        key="min_hold_on",
        help="매수 후 N회 리밸런싱이 지나기 전에는 순위 이탈해도 매도하지 않음.",
        on_change=reset_backtest_only,
    )
    if _hold_on:
        _min_hold = st.sidebar.slider(
            "최소 보유 (리밸런싱 횟수)",
            min_value=1,
            max_value=6,
            value=1,
            step=1,
            key="min_hold_n",
            on_change=reset_backtest_only,
        )
    _adv_on = st.sidebar.checkbox(
        "ADV 참여 한도 (매수)",
        value=True,
        key="adv_cap_on",
        help="종목당 매수액을 20일 평균 거래대금의 X% 이하로 제한 (시장충격 완화).",
        on_change=reset_backtest_only,
    )
    if _adv_on:
        _adv_pct = (
            st.sidebar.slider(
                "ADV 최대 참여 (%)",
                min_value=5,
                max_value=50,
                value=20,
                step=5,
                key="adv_cap_pct_ui",
                help="예: 20 = 일평균 거래대금의 0.2%가 아니라 20%. 개인 규모면 보통 여유.",
                on_change=reset_backtest_only,
            )
            / 100.0
        )
        # UI는 %로 보여주되, 실무 1~2%도 선택 가능하게 별도 미세 옵션
        _adv_fine = st.sidebar.checkbox(
            "ADV를 1-2% 미세 한도로 (기관식)",
            value=False,
            key="adv_fine_on",
            help="체크 시 위 슬라이더 대신 1% 또는 2% 고정.",
            on_change=reset_backtest_only,
        )
        if _adv_fine:
            _adv_pct = (
                st.sidebar.selectbox(
                    "ADV 미세 한도",
                    [0.01, 0.02],
                    index=0,
                    format_func=lambda x: f"{x*100:.0f}%",
                    key="adv_fine_val",
                    on_change=reset_backtest_only,
                )
            )
    _sec_on = st.sidebar.checkbox(
        "섹터 비중 캡",
        value=False,
        key="sector_cap_on",
        help="단일 섹터 목표 비중이 상한을 넘으면 해당 섹터 신규 매수를 스킵.",
        on_change=reset_backtest_only,
    )
    if _sec_on:
        _sec_cap = (
            st.sidebar.slider(
                "섹터 최대 비중 (%)",
                min_value=15,
                max_value=50,
                value=30,
                step=5,
                key="sector_cap_pct",
                on_change=reset_backtest_only,
            )
            / 100.0
        )
    _mdd_on = st.sidebar.checkbox(
        "MDD 킬스위치 (신규 매수 중단)",
        value=False,
        key="mdd_halt_on",
        help="자산이 고점 대비 설정 % 이상 하락하면 그 리밸런싱에서는 매수만 막고, 매도·트림은 허용합니다.",
        on_change=reset_backtest_only,
    )
    if _mdd_on:
        _mdd_halt = st.sidebar.slider(
            "매수 중단 MDD (%)",
            min_value=5,
            max_value=40,
            value=15,
            step=1,
            key="mdd_halt_pct",
            help="예: 15 = 고점 대비 -15% 이하면 신규 매수 중단.",
            on_change=reset_backtest_only,
        )
    else:
        _mdd_halt = 0.0

TRADE_RULES = TradeRules(
    buy_n=int(_buy_n),
    hold_n=int(_hold_n),
    stock_cap=(float(_cap_pct) / 100.0) if _cap_on else 0.0,
    rebalance_months=int(_freq_months),
    turnover_cap=float(_turn_cap),
    min_hold_cycles=int(_min_hold),
    adv_max_pct=float(_adv_pct),
    sector_cap=float(_sec_cap),
    mdd_halt_pct=float(_mdd_halt),
    max_positions=int(_max_positions),
)
st.sidebar.caption(f"적용: {TRADE_RULES.summary()}")


def calculate_rank(df):
    """
    결측(NaN) 처리:
    - PER/PBR 등 '낮을수록 좋음' · ROE 등 '높을수록 좋음' 모두
      na_option='bottom' → 결측은 해당 팩터에서 최하위.
    - 예전에 fillna(0) 후 PER 오름차순 랭크하면 결측(=0)이 1등이 되는 버그가 있었음.
    """
    def _wr(series, ascending, weight):
        # weight==0 이면 float 0.0 을 더하면 val_rank 전체가 float 가 되어 .rank() 실패
        if weight == 0:
            return pd.Series(0.0, index=df.index)
        return series.rank(ascending=ascending, method="average", na_option="bottom") * weight

    val_rank = (
        _wr(df["per"], True, f_per)
        + _wr(df["pbr"], True, f_pbr)
        + _wr(df["psr"], True, f_psr)
        + _wr(df["ev_ebitda"], True, f_ev)
        + _wr(df["per_sec"] if "per_sec" in df.columns else pd.Series(np.nan, index=df.index), True, f_per_sec)
        + _wr(df["pbr_sec"] if "pbr_sec" in df.columns else pd.Series(np.nan, index=df.index), True, f_pbr_sec)
    )
    qual_rank = (
        _wr(df["roe"], False, f_roe)
        + _wr(df["op_margin"], False, f_opm)
        + _wr(df["gross_margin"], False, f_gpm)
        + _wr(df["f_score"], False, f_fscore)
        + _wr(df["vol_12m"] if "vol_12m" in df.columns else pd.Series(np.nan, index=df.index), True, f_vol)
        + _wr(df["accrual"] if "accrual" in df.columns else pd.Series(np.nan, index=df.index), True, f_accrual)
        + _wr(df["fcf_yield"] if "fcf_yield" in df.columns else pd.Series(np.nan, index=df.index), False, f_fcf)
        + _wr(df["growth_stab"] if "growth_stab" in df.columns else pd.Series(np.nan, index=df.index), False, f_growth)
        + _wr(df["div_yield"] if "div_yield" in df.columns else pd.Series(np.nan, index=df.index), False, f_div)
        + _wr(df["share_growth"] if "share_growth" in df.columns else pd.Series(np.nan, index=df.index), True, f_share)
        + _wr(df["treasury_chg"] if "treasury_chg" in df.columns else pd.Series(np.nan, index=df.index), False, f_treasury)
    )
    earn_s = df["earn_mom"] if "earn_mom" in df.columns else pd.Series(np.nan, index=df.index)
    factor_s = df["factor_mom"] if "factor_mom" in df.columns else pd.Series(np.nan, index=df.index)
    mom_rank = (
        _wr(df["mom_1m"], False, f_mom1)
        + _wr(df["mom_6m"], False, f_mom6)
        + _wr(df["mom_12m"], False, f_mom12)
        + _wr(earn_s, False, f_earn_mom)
        + _wr(factor_s, False, f_factor_mom)
    )

    # 내부 랭크합(낮을수록 우위) → 화면용 0~100점(높을수록 우위)
    df["가치점수"] = ((1 - val_rank.rank(pct=True, ascending=True)) * 100).round(1)
    df["우량점수"] = ((1 - qual_rank.rank(pct=True, ascending=True)) * 100).round(1)
    df["모멘텀점수"] = ((1 - mom_rank.rank(pct=True, ascending=True)) * 100).round(1)
    df["Total_Rank_Score"] = val_rank + qual_rank + mom_rank
    df["종합점수"] = (
        df["가치점수"] * real_w_val
        + df["우량점수"] * real_w_qual
        + df["모멘텀점수"] * real_w_mom
    ).round(2)
    # 가치 팩터 전무(전부 결측)면 커버리지 표시용
    value_cols = ["per", "pbr", "psr", "ev_ebitda"]
    df["가치커버"] = df[value_cols].notna().sum(axis=1)
    return df.sort_values(by="종합점수", ascending=False).reset_index(drop=True)


def assign_trade_actions(df_ranked: pd.DataFrame, rules=None) -> pd.DataFrame:
    """버퍼 룰에 따른 매수/유지/매도 액션."""
    from rebalance_rules import TradeRules, assign_actions_by_rules

    r = rules or TradeRules()
    return assign_actions_by_rules(df_ranked, r)


def load_portfolio_lock():
    if not os.path.exists(PORTFOLIO_LOCK_PATH):
        return None
    try:
        with open(PORTFOLIO_LOCK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_portfolio_lock(df_locked: pd.DataFrame, factor_month: str, weights: dict):
    os.makedirs(os.path.dirname(PORTFOLIO_LOCK_PATH), exist_ok=True)
    cols = ["순위", "ticker", "종목명", "섹터", "가치점수", "우량점수", "모멘텀점수", "종합점수", "액션"]
    rows = df_locked.head(50)[[c for c in cols if c in df_locked.columns]].copy()
    payload = {
        "locked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "factor_month": factor_month,
        "weights": weights,
        "rows": rows.to_dict(orient="records"),
    }
    with open(PORTFOLIO_LOCK_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


# 유동성 필터 적용 (최신 팩터월 기준)
_liq_n_before = len(df_main)
_liq_note = "유동성 필터 꺼짐"
if liq_filter_on:
    try:
        from liquidity_benchmark import describe_liq_filter, filter_liquid_universe

        asof_liq = None
        if not df_price_all.empty:
            asof_liq = df_price_all["date"].max()
        ok = filter_liquid_universe(
            df_price_all,
            min_avg_tv_won=MIN_TV_WON,
            tv_bottom_pct=tv_bottom_pct,
            marcap_by_ticker=_LIQ_MARCAP_MAP or None,
            marcap_bottom_pct=marcap_bottom_pct,
            asof=asof_liq,
            lookback=20,
            universe=set(df_main["ticker"].astype(str)),
        )
        _liq_note = describe_liq_filter(
            min_tv_eok=min_tv_eok,
            tv_bottom_pct=tv_bottom_pct,
            marcap_bottom_pct=marcap_bottom_pct,
            marcap_source=_LIQ_MARCAP_SRC,
        )
        if ok:
            df_main = df_main[df_main["ticker"].isin(ok)].copy()
            st.sidebar.caption(
                f"유동성 통과: **{len(df_main):,}** / {_liq_n_before:,} · {_liq_note}"
            )
        else:
            st.sidebar.warning("거래량 데이터 부족 — 유동성 필터를 적용하지 못했습니다.")
    except Exception as e:
        st.sidebar.warning(f"유동성 필터 실패: {e}")

df_result = calculate_rank(df_main.copy())
df_result.insert(0, '순위', df_result.index + 1)
df_result = assign_trade_actions(df_result, TRADE_RULES)

# 제품 #6: AI 매크로 직후 월간 보고서 생성
if st.session_state.get("pending_monthly_report"):
    with st.spinner("이달의 AI 보고서 작성 중... (시황 요약 추가 호출)"):
        try:
            from monthly_report import generate_and_save_report

            wrep = st.session_state.get("_report_weights") or {
                "value": st.session_state.get("w_val", 34),
                "quality": st.session_state.get("w_qual", 33),
                "momentum": st.session_state.get("w_mom", 33),
                "reason": st.session_state.get("ai_reason", ""),
                "sub_value": {},
                "sub_quality": {},
                "sub_momentum": {},
                "source": "session",
            }
            # 세션 세부 슬라이더로 sub_* 보강
            wrep = dict(wrep)
            wrep["sub_value"] = {
                "per": st.session_state.get("sub_per", 25),
                "pbr": st.session_state.get("sub_pbr", 25),
                "psr": st.session_state.get("sub_psr", 15),
                "ev": st.session_state.get("sub_ev", 15),
                "per_sec": st.session_state.get("sub_per_sec", 10),
                "pbr_sec": st.session_state.get("sub_pbr_sec", 10),
            }
            wrep["sub_quality"] = {
                "roe": st.session_state.get("sub_roe", 12),
                "opm": st.session_state.get("sub_opm", 7),
                "gpm": st.session_state.get("sub_gpm", 7),
                "fscore": st.session_state.get("sub_fscore", 7),
                "vol": st.session_state.get("sub_vol", 10),
                "accrual": st.session_state.get("sub_accrual", 9),
                "fcf": st.session_state.get("sub_fcf", 9),
                "growth": st.session_state.get("sub_growth", 10),
                "div": st.session_state.get("sub_div", 9),
                "share": st.session_state.get("sub_share", 8),
                "treasury": st.session_state.get("sub_treasury", 12),
            }
            wrep["sub_momentum"] = {
                "price": st.session_state.get("sub_price_mom", 40),
                "earn": st.session_state.get("sub_earn_mom", 35),
                "factor": st.session_state.get("sub_factor_mom", 25),
                "mom1": st.session_state.get("sub_mom1", 20),
                "mom6": st.session_state.get("sub_mom6", 40),
                "mom12": st.session_state.get("sub_mom12", 40),
            }
            liq_note = _liq_note if liq_filter_on else "유동성 필터 꺼짐"
            cols_rep = [
                c
                for c in (
                    "순위", "종목명", "섹터", "가치점수", "우량점수", "모멘텀점수", "종합점수", "ticker"
                )
                if c in df_result.columns
            ]
            top_rows = df_result.head(10)[cols_rep].to_dict(orient="records")
            md = generate_and_save_report(
                wrep, top_rows, str(latest_date), db_date, liq_note=liq_note
            )
            st.session_state.monthly_report_md = md
            st.session_state.show_monthly_report = True
        except Exception as e:
            st.warning(f"월간 보고서 생성 실패: {e}")
        finally:
            st.session_state.pending_monthly_report = False


def _show_monthly_report_dialog():
    md = st.session_state.get("monthly_report_md") or ""
    st.markdown(md)
    if _CAN_USE_MEMBER_FEATURES:
        st.download_button(
            "⬇️ 마크다운 다운로드",
            data=md.encode("utf-8"),
            file_name=f"quant_lab_report_{latest_date}.md",
            mime="text/markdown",
            use_container_width=True,
        )
    else:
        st.info("🔒 보고서 다운로드는 로그인 후 이용할 수 있습니다. (열람은 가능)")
    if st.button("닫기", key="close_monthly_report", use_container_width=True):
        st.session_state.show_monthly_report = False
        st.rerun()


if st.session_state.get("show_monthly_report") and st.session_state.get("monthly_report_md"):
    try:
        @st.dialog("📄 이달의 퀀트 랩 리포트", width="large")
        def _monthly_report_dialog():
            _show_monthly_report_dialog()

        _monthly_report_dialog()
    except Exception:
        with st.expander("📄 이달의 퀀트 랩 리포트", expanded=True):
            _show_monthly_report_dialog()

# ==========================================
# 5. 점진적 공개(Progressive Disclosure) UI
# ==========================================

# --- 제품 #5: 시장 국면 레이더 (FDR 일봉, 5분 캐시) ---
@st.cache_data(ttl=300, show_spinner=False)
def _cached_kospi_regime():
    from market_regime import compute_kospi_regime
    return compute_kospi_regime(60)

try:
    _rg = _cached_kospi_regime()
except Exception as _e:
    _rg = {"ok": False, "error": str(_e)}

if _rg.get("ok"):
    _chg = float(_rg["chg"])
    _dd = float(_rg["dd_pct"])
    _chg_color = "#3DDC97" if _chg >= 0 else "#FF6B6B"
    _dd_color = "#FF6B6B" if _dd < -5 else "#F0C674"
    _arrow = "↑" if _chg >= 0 else "↓"
    _fetched = datetime.now().strftime("%H:%M")
    st.markdown(
        f"""
<div style="
  background: linear-gradient(180deg,#1a1c1e 0%,#121314 100%);
  border-radius: 16px; padding: 20px 22px 16px 22px; margin-bottom: 1rem;
  border: 1px solid rgba(255,255,255,0.06);">
  <div style="color:#fff;font-size:1.25rem;font-weight:700;margin-bottom:14px;">
    📡 시장 국면 레이더
    <span style="color:#888;font-size:0.75rem;font-weight:400;margin-left:8px;">
      KOSPI 일봉 · 데이터일 {_rg['asof']} · 화면갱신 {_fetched} (약 5분 캐시 · 호가 실시간 아님)
    </span>
  </div>
  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    <div style="flex:1;min-width:160px;">
      <div style="color:#9aa0a6;font-size:0.8rem;">현재 KOSPI 지수</div>
      <div style="color:#fff;font-size:1.75rem;font-weight:700;">{_rg['kospi']:,.2f}</div>
      <span style="background:rgba(61,220,151,0.15);color:{_chg_color};
        padding:2px 10px;border-radius:999px;font-size:0.85rem;">
        {_arrow} {_chg:+.2f} ({_rg['chg_pct']:+.2f}%)
      </span>
    </div>
    <div style="flex:1;min-width:160px;">
      <div style="color:#9aa0a6;font-size:0.8rem;">시장 심리 국면</div>
      <div style="color:#fff;font-size:1.55rem;font-weight:700;">
        {_rg['regime']} {_rg['emoji']}
      </div>
    </div>
    <div style="flex:1;min-width:180px;">
      <div style="color:#9aa0a6;font-size:0.8rem;">최근 {_rg['dd_lookback']}일 고점 대비 낙폭(DD)</div>
      <div style="color:#fff;font-size:1.75rem;font-weight:700;">{_dd:.2f}%</div>
      <span style="background:rgba(255,107,107,0.15);color:{_dd_color};
        padding:2px 10px;border-radius:999px;font-size:0.85rem;">
        ↓ {_dd:.2f}%
      </span>
    </div>
  </div>
  <div style="
    margin-top:16px;padding:12px 14px;border-radius:10px;
    background:rgba(120,40,40,0.45);color:#ffc9c9;font-size:0.95rem;">
    ⚠️ {_rg['advice']}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
else:
    st.info(f"📡 시장 국면 레이더: {_rg.get('error', '데이터 없음')}")

# --- 제품 #5-b: 코스피 대비 상대강도 (방어 / 상승 곡선) ---
@st.cache_data(ttl=300, show_spinner="상대강도 계산 중…")
def _cached_relative_strength(price_asof: str, tickers: tuple):
    from relative_strength import compute_relative_strength

    if not tickers or not price_asof:
        return pd.DataFrame()
    cut = (pd.Timestamp(price_asof) - pd.Timedelta(days=200)).strftime("%Y-%m-%d")
    conn = sqlite3.connect("data_cache/quant_history.db")
    try:
        ph = ",".join("?" * len(tickers))
        sub = pd.read_sql(
            f"SELECT date, ticker, close FROM daily_price "
            f"WHERE date >= ? AND ticker IN ({ph})",
            conn,
            params=[cut, *tickers],
        )
    except Exception:
        sub = pd.DataFrame()
    finally:
        conn.close()
    if sub.empty:
        return pd.DataFrame()
    sub["date"] = pd.to_datetime(sub["date"])
    sub["close"] = pd.to_numeric(sub["close"], errors="coerce")
    return compute_relative_strength(sub, tickers=list(tickers))


with st.expander("📈 코스피 대비 상대강도 · 방어/상승 종목 (#5-b)", expanded=True):
    st.caption(
        "RS = 종목수익률 − 코스피수익률. "
        "**버티는 종목**은 지수보다 덜 빠진 종목, **상승 곡선**은 RS가 높은 종목입니다. "
        "(일봉·약 5분 캐시 · 투자자문 아님)"
    )
    _rs_universe = (
        df_result.sort_values("종합점수", ascending=False)["ticker"]
        .astype(str)
        .head(400)
        .tolist()
    )
    _price_asof = (
        str(pd.to_datetime(df_price_all["date"].max()).date())
        if not df_price_all.empty
        else ""
    )
    try:
        _df_rs = _cached_relative_strength(_price_asof, tuple(_rs_universe))
    except Exception as _rs_err:
        _df_rs = pd.DataFrame()
        st.warning(f"상대강도 계산 실패: {_rs_err}")

    if _df_rs is not None and not _df_rs.empty:
        from relative_strength import top_defensive, top_offensive

        _name_map = dict(
            zip(df_result["ticker"].astype(str), df_result["종목명"].astype(str))
        )
        _sec_map = dict(
            zip(df_result["ticker"].astype(str), df_result["섹터"].astype(str))
        )
        _def = top_defensive(_df_rs, 15).copy()
        _off = top_offensive(_df_rs, 15).copy()
        for _d in (_def, _off):
            _d["종목명"] = _d["ticker"].map(_name_map).fillna(_d["ticker"])
            _d["섹터"] = _d["ticker"].map(_sec_map).fillna("-")

        _regime_label = (_rg.get("regime") or "") if isinstance(_rg, dict) else ""
        if any(k in _regime_label for k in ("공포", "불안", "경계")):
            st.info(f"현재 국면 **{_regime_label}** → 방어(버티기) 종목을 우선 확인하세요.")
        elif "탐욕" in _regime_label or "과열" in _regime_label:
            st.info(f"현재 국면 **{_regime_label}** → 상승 곡선 추격보다 방어·우량도 함께 보세요.")
        elif _regime_label:
            st.caption(f"현재 국면: {_regime_label} — 방어·상승 표를 함께 참고하세요.")

        c_def, c_off = st.columns(2)
        with c_def:
            st.markdown("#### 🛡️ 버티는 종목 (방어)")
            st.caption("지수 대비 낙폭 작음 + RS")
            st.dataframe(
                _def[
                    ["종목명", "섹터", "rs_20d", "rs_60d", "dd_60d", "dd_vs_kospi"]
                ].rename(
                    columns={
                        "rs_20d": "RS 20일(%)",
                        "rs_60d": "RS 60일(%)",
                        "dd_60d": "낙폭 60일(%)",
                        "dd_vs_kospi": "낙폭 우위(pp)",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
        with c_off:
            st.markdown("#### 🚀 상승 곡선 (공격)")
            st.caption("코스피 대비 초과수익(RS) 상위")
            st.dataframe(
                _off[["종목명", "섹터", "rs_20d", "rs_60d", "ret_60d"]].rename(
                    columns={
                        "rs_20d": "RS 20일(%)",
                        "rs_60d": "RS 60일(%)",
                        "ret_60d": "수익률 60일(%)",
                    }
                ),
                hide_index=True,
                width="stretch",
            )
        _asof_rs = (
            str(_df_rs["asof"].iloc[0]) if "asof" in _df_rs.columns else _price_asof
        )
        st.caption(f"기준일 {_asof_rs} · 유니버스 {len(_df_rs):,}종 (종합점수 Top 400)")
    else:
        st.info("상대강도 계산에 필요한 일봉/코스피 데이터가 부족합니다.")

st.markdown(f"### 📊 전략 요약 (기준월: {latest_date})")
col1, col2, col3, col4 = st.columns(4)
col1.metric("분석 대상 종목", f"{len(df_result):,} 개")
col2.metric("가치 비중", f"{real_w_val*100:.0f}%")
col3.metric("우량 비중", f"{real_w_qual*100:.0f}%")
col4.metric("모멘텀 비중", f"{real_w_mom*100:.0f}%")

st.divider()

if st.button("🚀 포트폴리오·예비 랭킹 보기", type="primary", width="stretch"):
    st.session_state.step1_unlocked = True
    st.session_state.step2_unlocked = False 

if st.session_state.step1_unlocked:
    display_cols = ['순위', '액션', '종목명', '섹터', '가치점수', '우량점수', '모멘텀점수', '종합점수']
    lock = load_portfolio_lock()

    # ---------- Block A: 이번 달 확정(고정) ----------
    st.markdown("### 📌 이번 달 확정 운용 포트폴리오")
    st.caption(
        "리밸런싱일에 잠근 포트폴리오입니다. **한 달간 매매 기준점으로 유지**됩니다. "
        "가중치를 바꿔도 여기 표는 다시 확정하기 전까지 변하지 않습니다."
    )
    lc1, lc2 = st.columns([2, 1])
    with lc1:
        if st.button("🔒 현재 종합점수 기준으로 이번 달 포트폴리오 확정", width="stretch"):
            if not _CAN_USE_MEMBER_FEATURES:
                st.warning("🔒 포트폴리오 확정은 로그인 후 이용할 수 있습니다. 우측 상단에서 가입/로그인해 주세요.")
            else:
                save_portfolio_lock(
                    df_result,
                    latest_date,
                    {
                        "value": round(real_w_val, 4),
                        "quality": round(real_w_qual, 4),
                        "momentum": round(real_w_mom, 4),
                        "user": (st.session_state.auth_user or {}).get("email")
                        or ("beta-guest" if _BETA_SKIP_AUTH_GATES else None),
                    },
                )
                st.success(f"확정 완료 — 기준월 {latest_date}")
                st.rerun()
    with lc2:
        if lock and st.button("🔓 확정 해제", width="stretch"):
            try:
                os.remove(PORTFOLIO_LOCK_PATH)
            except Exception:
                pass
            st.rerun()

    if lock and lock.get("rows"):
        df_locked = pd.DataFrame(lock["rows"])
        # 확정 순위·종목은 유지하되, 매수/유지/매도 라벨은 현재 사이드바 버퍼 룰로 재부여
        if "순위" in df_locked.columns:
            df_locked = assign_trade_actions(df_locked, TRADE_RULES)
        w = lock.get("weights") or {}
        st.info(
            f"확정 시각 **{lock.get('locked_at', '-')}** · 팩터월 **{lock.get('factor_month', '-')}** · "
            f"비중 V{w.get('value', 0)*100:.0f}/Q{w.get('quality', 0)*100:.0f}/M{w.get('momentum', 0)*100:.0f}"
        )
        st.caption(
            f"액션 구간은 지금 사이드바 룰 기준입니다: **{TRADE_RULES.summary()}** "
            "(종목 구성 자체를 바꾸려면 다시 확정하세요.)"
        )
        show_lock_cols = [c for c in display_cols if c in df_locked.columns]
        tab_buy, tab_hold, tab_sell = st.tabs([
            f"매수 (1-{TRADE_RULES.buy_n})",
            f"유지 ({TRADE_RULES.buy_n+1}-{TRADE_RULES.hold_n})",
            f"매도 후보 ({TRADE_RULES.hold_n+1}-{TRADE_RULES.sell_preview_to})",
        ])
        with tab_buy:
            buy_df = (
                df_locked[df_locked["액션"] == "매수"]
                if "액션" in df_locked.columns
                else df_locked[df_locked["순위"] <= TRADE_RULES.buy_n]
            )
            st.dataframe(buy_df[show_lock_cols], width="stretch", hide_index=True)
        with tab_hold:
            hold_df = (
                df_locked[df_locked["액션"] == "유지"]
                if "액션" in df_locked.columns
                else df_locked[
                    (df_locked["순위"] > TRADE_RULES.buy_n)
                    & (df_locked["순위"] <= TRADE_RULES.hold_n)
                ]
            )
            st.dataframe(hold_df[show_lock_cols], width="stretch", hide_index=True)
        with tab_sell:
            sell_df = (
                df_locked[df_locked["액션"] == "매도"]
                if "액션" in df_locked.columns
                else df_locked[
                    (df_locked["순위"] > TRADE_RULES.hold_n)
                    & (df_locked["순위"] <= TRADE_RULES.sell_preview_to)
                ]
            )
            st.dataframe(sell_df[show_lock_cols], width="stretch", hide_index=True)
    else:
        st.warning("아직 확정된 운용 포트폴리오가 없습니다. 위에서 **확정**을 누르면 이번 달 기준점이 잠깁니다.")

    st.divider()

    # ---------- Block B: 실시간 예비 랭킹 ----------
    st.markdown("### 👀 실시간 예비 랭킹 (참고용)")
    st.caption(
        "최신 팩터·사이드바 비중으로 **매일(데이터 갱신 시) 다시 계산**되는 참고 랭킹입니다. "
        "바로 매매하지 말고, 다음 리밸런싱 후보를 보는 용도로 쓰세요."
    )
    with st.expander("🔽 예비 Top 20 · 종합점수", expanded=True):
        show_df = df_result.head(20)[display_cols].copy()
        st.dataframe(show_df, width="stretch", hide_index=True)
        st.caption(
            f"✔️ **종합점수 = 가치×비중 + 우량×비중 + 모멘텀×비중** · 정렬: 종합점수 높은 순 · "
            f"액션: {TRADE_RULES.summary()}"
        )

        # 확정 대비 변동 (있으면)
        if lock and lock.get("rows"):
            locked_tickers = {r.get("ticker") for r in lock["rows"] if r.get("순위", 99) <= 20}
            live_top20 = set(df_result.head(20)["ticker"].tolist()) if "ticker" in df_result.columns else set()
            entered = live_top20 - locked_tickers
            exited = locked_tickers - live_top20
            if entered or exited:
                c_in, c_out = st.columns(2)
                with c_in:
                    names_in = df_result[df_result["ticker"].isin(entered)]["종목명"].tolist() if entered else []
                    st.write("**신규 진입 후보 (예비 Top20)**", ", ".join(names_in) if names_in else "-")
                with c_out:
                    lock_df = pd.DataFrame(lock["rows"])
                    names_out = lock_df[lock_df["ticker"].isin(exited)]["종목명"].tolist() if exited and "종목명" in lock_df.columns else []
                    st.write("**이탈 후보 (확정 Top20 대비)**", ", ".join(names_out) if names_out else "-")

        with st.expander("🔒 세부 재무·모멘텀 원천 지표 (유료 구독 예정)", expanded=False):
            st.info("상세 원천 지표(PER/PBR/ROE 등)는 향후 유료 구독 티어에서 제공합니다. 현재는 미리보기용으로만 노출됩니다.")
            detail_cols = [
                c for c in [
                    '순위', '종목명',
                    'per', 'pbr', 'psr', 'ev_ebitda', 'per_sec', 'pbr_sec',
                    'roe', 'op_margin', 'gross_margin', 'f_score', 'vol_12m', 'accrual', 'fcf_yield', 'growth_stab',
                    'div_yield', 'share_growth', 'treasury_chg',
                    'sales_g1y', 'op_g1y', 'ni_g1y', 'earn_surprise',
                    'mom_1m', 'mom_6m', 'mom_12m', 'earn_mom', 'factor_mom'
                ] if c in df_result.columns
            ]
            detail_df = df_result.head(20)[detail_cols].copy()
            num_cols = [c for c in detail_cols if c not in ("순위", "종목명")]
            # 화면의 0과 결측 구분: 결측은 빈칸
            detail_df[num_cols] = detail_df[num_cols].round(2)
            st.dataframe(detail_df, width="stretch", hide_index=True)
            miss = int((df_result.head(20)["가치커버"] == 0).sum()) if "가치커버" in df_result.columns else 0
            st.caption(
                f"⚠️ Top20 중 가치지표(PER/PBR/PSR/EV)가 전부 결측인 종목: **{miss}**개. "
                "결측은 랭킹에서 최하위로 처리됩니다(0으로 채워 우대하지 않음)."
            )
    
    st.divider()
    st.markdown("### 📈 Step 2: 실전 다이내믹 시계열 백테스터")
    st.info(
        "💡 **알림**: 팩터 스냅샷은 월별이며, **매매 리밸런싱 주기는 사이드바**(월/분기/반기)를 따릅니다. "
        "자산 평가는 매일 종가 · 적립금은 매월 첫 거래일 투입입니다."
    )
    st.caption(f"✔️ 투자 룰: {TRADE_RULES.summary()} · 백테스트는 사이드바와 동일 규칙")
    st.caption("💸 수수료 및 슬리피지: 매수 시 0.15%, 매도 시 0.30% (세금 포함) 적용 · 적립금은 매월 투입, 매매만 리밸런싱 주기")
    
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
            with st.spinner("일별 주가 Mark-to-Market + 주기별 다이내믹 리밸런싱 연산 중..."):
                from rebalance_rules import (
                    apply_min_hold_to_sells,
                    clip_trades_by_turnover,
                    filter_buys_by_max_positions,
                    filter_buys_by_sector_cap,
                    is_calendar_rebalance_month,
                    max_buy_value_by_adv,
                )
                from liquidity_benchmark import avg_trading_value as _avg_tv

                FEE_BUY = 0.0015
                FEE_SELL = 0.0030
                CAP_LIMIT = TRADE_RULES.stock_cap
                BUY_N = TRADE_RULES.buy_n
                HOLD_N = TRADE_RULES.hold_n
                TARGET_W = TRADE_RULES.target_weight
                REBAL_M = TRADE_RULES.rebalance_months
                TURN_CAP = TRADE_RULES.turnover_cap
                MIN_HOLD = TRADE_RULES.min_hold_cycles
                ADV_PCT = TRADE_RULES.adv_max_pct
                SEC_CAP = TRADE_RULES.sector_cap
                MDD_HALT = TRADE_RULES.mdd_halt_pct
                MAX_POS = TRADE_RULES.max_positions
                
                df_history = df_all.copy()
                val_hist = (
                    df_history.groupby("date")["per"].rank(ascending=True, na_option="bottom") * f_per
                    + df_history.groupby("date")["pbr"].rank(ascending=True, na_option="bottom") * f_pbr
                    + df_history.groupby("date")["psr"].rank(ascending=True, na_option="bottom") * f_psr
                    + df_history.groupby("date")["ev_ebitda"].rank(ascending=True, na_option="bottom") * f_ev
                    + (
                        df_history.groupby("date")["per_sec"].rank(ascending=True, na_option="bottom") * f_per_sec
                        if "per_sec" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["pbr_sec"].rank(ascending=True, na_option="bottom") * f_pbr_sec
                        if "pbr_sec" in df_history.columns else 0
                    )
                )
                qual_hist = (
                    df_history.groupby("date")["roe"].rank(ascending=False, na_option="bottom") * f_roe
                    + df_history.groupby("date")["op_margin"].rank(ascending=False, na_option="bottom") * f_opm
                    + df_history.groupby("date")["gross_margin"].rank(ascending=False, na_option="bottom") * f_gpm
                    + df_history.groupby("date")["f_score"].rank(ascending=False, na_option="bottom") * f_fscore
                    + (
                        df_history.groupby("date")["vol_12m"].rank(ascending=True, na_option="bottom") * f_vol
                        if "vol_12m" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["accrual"].rank(ascending=True, na_option="bottom") * f_accrual
                        if "accrual" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["fcf_yield"].rank(ascending=False, na_option="bottom") * f_fcf
                        if "fcf_yield" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["growth_stab"].rank(ascending=False, na_option="bottom") * f_growth
                        if "growth_stab" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["div_yield"].rank(ascending=False, na_option="bottom") * f_div
                        if "div_yield" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["share_growth"].rank(ascending=True, na_option="bottom") * f_share
                        if "share_growth" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["treasury_chg"].rank(ascending=False, na_option="bottom") * f_treasury
                        if "treasury_chg" in df_history.columns else 0
                    )
                )
                mom_hist = (
                    df_history.groupby("date")["mom_1m"].rank(ascending=False, na_option="bottom") * f_mom1
                    + df_history.groupby("date")["mom_6m"].rank(ascending=False, na_option="bottom") * f_mom6
                    + df_history.groupby("date")["mom_12m"].rank(ascending=False, na_option="bottom") * f_mom12
                    + (
                        df_history.groupby("date")["earn_mom"].rank(ascending=False, na_option="bottom") * f_earn_mom
                        if "earn_mom" in df_history.columns else 0
                    )
                    + (
                        df_history.groupby("date")["factor_mom"].rank(ascending=False, na_option="bottom") * f_factor_mom
                        if "factor_mom" in df_history.columns else 0
                    )
                )

                # 월별 종합점수(0~100 가중합) → 높을수록 1위 (매수/유지/매도 기준)
                df_history['_val'] = val_hist
                df_history['_qual'] = qual_hist
                df_history['_mom'] = mom_hist
                df_history['가치점수'] = (
                    1 - df_history.groupby('date')['_val'].rank(pct=True, ascending=True)
                ) * 100
                df_history['우량점수'] = (
                    1 - df_history.groupby('date')['_qual'].rank(pct=True, ascending=True)
                ) * 100
                df_history['모멘텀점수'] = (
                    1 - df_history.groupby('date')['_mom'].rank(pct=True, ascending=True)
                ) * 100
                df_history['종합점수'] = (
                    df_history['가치점수'] * real_w_val
                    + df_history['우량점수'] * real_w_qual
                    + df_history['모멘텀점수'] * real_w_mom
                )
                df_history['Rank'] = df_history.groupby('date')['종합점수'].rank(
                    ascending=False, method='first'
                )
                
                # 일별 주가 시계열 슬라이싱 (팩터 시작월 이전은 리밸런싱 불가 → 자동 클램프)
                all_dates = sorted(pd.to_datetime(df_price_all['date'].unique()))
                max_date = all_dates[-1]
                user_start = max_date - pd.DateOffset(years=invest_years)
                factor_start_ts = pd.Timestamp(str(factor_start) + '-01')
                start_date = max(user_start, factor_start_ts)
                if start_date > user_start:
                    st.warning(
                        f"⚠️ 월별 팩터 DB가 **{factor_start}**부터만 존재합니다. "
                        f"요청하신 {invest_years}년 구간 대신 **{start_date.date()} ~ {max_date.date()}**로 백테스트를 실행합니다."
                    )
                available_dates = [d for d in all_dates if d >= start_date]
                
                _px_for_pivot = (
                    df_price_all[df_price_all['date'] >= start_date]
                    .drop_duplicates(subset=['date', 'ticker'], keep='last')
                )
                price_pivot = (
                    _px_for_pivot
                    .pivot(index='date', columns='ticker', values='close')
                    .sort_index()
                    .ffill()
                    .fillna(0)
                )

                # 주가 전처리 1회 (리밸런싱마다 전체 to_datetime/copy 방지)
                _px = df_price_all.drop_duplicates(subset=["date", "ticker"], keep="last").copy()
                _px["date"] = pd.to_datetime(_px["date"])
                _px = _px[_px["date"] >= start_date]
                if "volume" in _px.columns:
                    _px["close"] = pd.to_numeric(_px["close"], errors="coerce")
                    _px["volume"] = pd.to_numeric(_px["volume"], errors="coerce")
                _liq_ym_cache: dict = {}
                _tv_ym_cache: dict = {}
                
                cash = init_cap * 10000
                portfolio = {}
                asset_history = []
                invested_history = []
                date_history = []
                total_invested = cash
                first_buy_price = {}
                _bt_buy_fills = 0
                _bt_buy_skips_px = 0
                _bt_buy_skips_slot = 0
                _bt_max_positions = 0

                def _px_at(prices, ticker: str) -> float:
                    """Series/dict에서 종가 안전 조회 (결측·0 제외)."""
                    t = str(ticker)
                    try:
                        if hasattr(prices, "index") and t in prices.index:
                            v = prices[t]
                        elif hasattr(prices, "get"):
                            v = prices.get(t, 0)
                        else:
                            return 0.0
                        if v is None or (isinstance(v, float) and pd.isna(v)):
                            return 0.0
                        fv = float(v)
                        return fv if fv > 0 else 0.0
                    except Exception:
                        return 0.0
                
                last_ym = None
                buy_list, hold_list = [], []
                entry_cycle = {}
                rebal_cycle = 0
                peak_asset = cash
                _sector_of = {}
                if "섹터" in df_all.columns and "ticker" in df_all.columns:
                    _tmp = df_all.dropna(subset=["ticker"]).drop_duplicates("ticker")
                    for _, row in _tmp.iterrows():
                        _sector_of[str(row["ticker"])] = str(row["섹터"]) if pd.notna(row["섹터"]) else "기타"
                elif "sector" in df_all.columns and "ticker" in df_all.columns:
                    _tmp = df_all.dropna(subset=["ticker"]).drop_duplicates("ticker")
                    for _, row in _tmp.iterrows():
                        _sector_of[str(row["ticker"])] = str(row["sector"]) if pd.notna(row["sector"]) else "기타"

                for i, date in enumerate(available_dates):
                    if date not in price_pivot.index:
                        continue
                    current_prices = price_pivot.loc[date]
                    ym = pd.Timestamp(date).strftime("%Y-%m")

                    is_new_month = (last_ym is None) or (ym != last_ym)
                    is_rebalance = False
                    if is_new_month:
                        if last_ym is not None:
                            cash += monthly_cap * 10000
                            total_invested += monthly_cap * 10000
                        last_ym = ym
                        is_rebalance = is_calendar_rebalance_month(ym, REBAL_M) or (
                            len(buy_list) == 0
                        )

                        if is_rebalance:
                            past_data = df_history[df_history["date"] <= ym]
                            if not past_data.empty:
                                latest_past_date = past_data["date"].max()
                                monthly_data = df_history[df_history["date"] == latest_past_date].copy()
                                if liq_filter_on:
                                    try:
                                        from liquidity_benchmark import (
                                            filter_liquid_universe as _liq_filt,
                                        )
                                        if ym in _liq_ym_cache:
                                            ok_m = _liq_ym_cache[ym]
                                        else:
                                            ok_m = _liq_filt(
                                                _px,
                                                min_avg_tv_won=MIN_TV_WON,
                                                tv_bottom_pct=tv_bottom_pct,
                                                marcap_by_ticker=_LIQ_MARCAP_MAP or None,
                                                marcap_bottom_pct=marcap_bottom_pct,
                                                asof=pd.Timestamp(date),
                                                lookback=20,
                                                universe=set(monthly_data["ticker"].astype(str)),
                                            )
                                            _liq_ym_cache[ym] = ok_m
                                        if ok_m:
                                            monthly_data = monthly_data[
                                                monthly_data["ticker"].isin(ok_m)
                                            ].copy()
                                            monthly_data = monthly_data.sort_values(
                                                "종합점수", ascending=False
                                            )
                                            monthly_data["Rank"] = np.arange(1, len(monthly_data) + 1)
                                    except Exception:
                                        pass
                                buy_list = monthly_data[monthly_data["Rank"] <= BUY_N]["ticker"].tolist()
                                hold_list = monthly_data[
                                    (monthly_data["Rank"] > BUY_N) & (monthly_data["Rank"] <= HOLD_N)
                                ]["ticker"].tolist()

                    stock_value = sum(portfolio[t] * _px_at(current_prices, t) for t in portfolio)
                    total_asset = cash + stock_value
                    if total_asset > peak_asset:
                        peak_asset = total_asset

                    if is_rebalance and buy_list:
                        rebal_cycle += 1
                        avg_tv_map = {}
                        if ADV_PCT > 0:
                            try:
                                # 매수 후보만 ADV 계산 (전체 유니버스 스캔 방지)
                                _cand = set(str(t) for t in buy_list)
                                _ck = (ym, tuple(sorted(_cand)))
                                if _ck in _tv_ym_cache:
                                    avg_tv_map = _tv_ym_cache[_ck]
                                else:
                                    _s = _avg_tv(
                                        _px,
                                        asof=pd.Timestamp(date),
                                        lookback=20,
                                        tickers=_cand,
                                    )
                                    avg_tv_map = {
                                        str(k): float(v) for k, v in _s.items() if pd.notna(v)
                                    }
                                    _tv_ym_cache[_ck] = avg_tv_map
                            except Exception:
                                avg_tv_map = {}

                        raw_sells = {
                            t for t in portfolio
                            if t not in buy_list and t not in hold_list
                        }
                        to_sell, protected = apply_min_hold_to_sells(
                            raw_sells, entry_cycle, rebal_cycle, MIN_HOLD
                        )
                        hold_eff = list(hold_list) + list(protected)

                        bl = buy_list
                        if SEC_CAP > 0 and _sector_of:
                            bl = filter_buys_by_sector_cap(
                                buy_list, portfolio, current_prices, total_asset,
                                _sector_of, SEC_CAP, TARGET_W,
                            )

                        sell_plan = {}
                        for t in to_sell:
                            px = _px_at(current_prices, t)
                            if px > 0 and t in portfolio:
                                sell_plan[t] = portfolio[t] * px
                        for t in list(portfolio.keys()):
                            if t not in hold_eff:
                                continue
                            px = _px_at(current_prices, t)
                            if px <= 0 or CAP_LIMIT <= 0:
                                continue
                            w = (portfolio[t] * px) / total_asset if total_asset > 0 else 0
                            if w > CAP_LIMIT:
                                sell_plan[t] = sell_plan.get(t, 0) + (w - CAP_LIMIT) * total_asset

                        buy_plan = {}
                        for t in bl:
                            px = _px_at(current_prices, t)
                            if px <= 0:
                                _bt_buy_skips_px += 1
                                continue
                            cw = (portfolio.get(t, 0) * px) / total_asset if total_asset > 0 else 0
                            need = max(0.0, (TARGET_W - cw) * total_asset)
                            if ADV_PCT > 0:
                                adv_lim = max_buy_value_by_adv(t, avg_tv_map, ADV_PCT)
                                if adv_lim is not None:
                                    need = min(need, float(adv_lim))
                            if need > px:
                                buy_plan[t] = need

                        sell_plan, buy_plan = clip_trades_by_turnover(
                            sell_plan, buy_plan, total_asset, TURN_CAP
                        )

                        # MDD 킬스위치: 고점 대비 낙폭 한도 초과 시 신규 매수 중단
                        if MDD_HALT > 0 and peak_asset > 0:
                            dd_pct = (1.0 - total_asset / peak_asset) * 100.0
                            if dd_pct >= MDD_HALT:
                                buy_plan = {}

                        for t, target_val in sell_plan.items():
                            px = _px_at(current_prices, t)
                            if px <= 0 or t not in portfolio:
                                continue
                            sell_shares = min(int(portfolio[t]), int(target_val / px))
                            if sell_shares <= 0:
                                continue
                            cash += sell_shares * px * (1 - FEE_SELL)
                            portfolio[t] -= sell_shares
                            if portfolio[t] <= 0:
                                del portfolio[t]
                                entry_cycle.pop(t, None)

                        stock_value = sum(portfolio[t] * _px_at(current_prices, t) for t in portfolio)
                        total_asset = cash + stock_value

                        # 매도 반영 후 슬롯 기준으로 신규 편입만 제한
                        if MAX_POS > 0 and buy_plan:
                            _ordered = [t for t in bl if t in buy_plan]
                            _allowed = set(
                                filter_buys_by_max_positions(_ordered, portfolio, MAX_POS)
                            )
                            _bt_buy_skips_slot += sum(
                                1
                                for t in buy_plan
                                if t not in _allowed and t not in portfolio
                            )
                            buy_plan = {t: v for t, v in buy_plan.items() if t in _allowed}

                        for t, budget in buy_plan.items():
                            px = _px_at(current_prices, t)
                            if px <= 0:
                                continue
                            actual = min(budget, cash)
                            if actual <= px:
                                continue
                            buy_shares = int(actual / (px * (1 + FEE_BUY)))
                            if buy_shares <= 0:
                                continue
                            portfolio[t] = portfolio.get(t, 0) + buy_shares
                            cash -= buy_shares * px * (1 + FEE_BUY)
                            _bt_buy_fills += 1
                            if t not in entry_cycle:
                                entry_cycle[t] = rebal_cycle
                            if t not in first_buy_price:
                                first_buy_price[t] = px

                    final_stock_value = sum(portfolio[t] * _px_at(current_prices, t) for t in portfolio)
                    _bt_max_positions = max(_bt_max_positions, len(portfolio))
                    date_history.append(pd.Timestamp(date))
                    asset_history.append(cash + final_stock_value)
                    invested_history.append(total_invested)

                if not date_history:
                    st.error("선택한 기간에 유효한 일별 주가/팩터 교집합이 없습니다.")
                    st.stop()

                df_asset = pd.DataFrame({
                    'Total_Value': asset_history,
                    'Total_Invested': invested_history
                }, index=pd.DatetimeIndex(date_history))
                final_val = df_asset['Total_Value'].iloc[-1]
                years = max((df_asset.index[-1] - df_asset.index[0]).days / 365.25, 1 / 365.25)
                cagr = ((final_val / total_invested) ** (1 / years) - 1) * 100 if total_invested > 0 else 0
                
                df_asset['HWM'] = df_asset['Total_Value'].cummax()
                df_asset['Drawdown'] = (df_asset['Total_Value'] / df_asset['HWM'] - 1) * 100
                mdd = df_asset['Drawdown'].min()

                # 진단: 적립금만 쌓인 직선(미매수) 감지
                _corr = float(
                    df_asset["Total_Value"].corr(df_asset["Total_Invested"])
                ) if len(df_asset) > 3 else 1.0
                _ret_std = float(df_asset["Total_Value"].pct_change().std() or 0)
                if _bt_buy_fills == 0 or _bt_max_positions == 0:
                    st.error(
                        f"⚠️ 백테스트에서 주식 매수가 거의/전혀 없었습니다 "
                        f"(체결 {_bt_buy_fills}회, 최대 보유 {_bt_max_positions}종목, "
                        f"가격0 스킵 {_bt_buy_skips_px}). "
                        "자산 곡선이 누적 원금과 같은 직선으로 보입니다. "
                        "유동성·ADV 한도를 끄거나 완화한 뒤 다시 실행해 보세요."
                    )
                elif _corr > 0.995 and _ret_std < 0.002:
                    st.warning(
                        f"자산 곡선이 누적 원금과 거의 같습니다 "
                        f"(상관 {_corr:.3f}, 일간변동 {_ret_std:.4f}, 매수체결 {_bt_buy_fills}회). "
                        "제약이 과도하거나 주가 매칭이 약한 구간일 수 있습니다."
                    )
                else:
                    st.caption(
                        f"시뮬레이션 요약: 매수체결 {_bt_buy_fills}회 · "
                        f"최대 보유 {_bt_max_positions}종목 · 가격결측 스킵 {_bt_buy_skips_px}"
                        + (
                            f" · 슬롯제한 신규스킵 {_bt_buy_skips_slot}"
                            if MAX_POS > 0
                            else ""
                        )
                    )
                
                show_volatility = st.toggle(
                    "🚨 주요 하락장/고변동성 구간 차트에 음영 표시 (MDD -10% 기준)",
                    help="낙폭 -10% 이하 구간만 붉은 음영으로 표시합니다. (라벨 중복 없이 가시성 우선)"
                )
                bc_kospi = st.checkbox("코스피 지수 오버레이 (시작=100)", value=True, key="bt_kospi")
                bc_kosdaq = st.checkbox("코스닥 지수 오버레이 (시작=100)", value=True, key="bt_kosdaq")
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_asset.index,
                    y=df_asset['Total_Invested'],
                    mode='lines',
                    name='누적 투자 원금',
                    line=dict(color='rgba(150, 150, 150, 0.7)', width=2, dash='dash')
                ))
                fig.add_trace(go.Scatter(
                    x=df_asset.index,
                    y=df_asset['Total_Value'],
                    mode='lines',
                    name='나의 퀀트 랩 자산',
                    line=dict(color='#00CC96', width=2.5)
                ))

                # #11: 코스피/코스닥 보조축 (시작일=100 으로 지수화)
                if bc_kospi or bc_kosdaq:
                    try:
                        from liquidity_benchmark import load_kr_benchmarks

                        @st.cache_data(ttl=86400, show_spinner=False)
                        def _bench(start: str, end: str):
                            return load_kr_benchmarks(start, end)

                        bdf = _bench(
                            df_asset.index.min().strftime("%Y-%m-%d"),
                            df_asset.index.max().strftime("%Y-%m-%d"),
                        )
                        if not bdf.empty:
                            bdf = bdf.reindex(df_asset.index).ffill()
                            colors = {"코스피": "#636EFA", "코스닥": "#EF553B"}
                            for col, on in (("코스피", bc_kospi), ("코스닥", bc_kosdaq)):
                                if not on or col not in bdf.columns:
                                    continue
                                s = pd.to_numeric(bdf[col], errors="coerce").dropna()
                                if s.empty:
                                    continue
                                rebased = bdf[col] / float(s.iloc[0]) * 100.0
                                fig.add_trace(
                                    go.Scatter(
                                        x=df_asset.index,
                                        y=rebased,
                                        mode="lines",
                                        name=f"{col} (시작=100)",
                                        line=dict(color=colors.get(col, "#AB63FA"), width=1.5, dash="dot"),
                                        yaxis="y2",
                                    )
                                )
                    except Exception as e:
                        st.caption(f"⚠️ 벤치마크 지수 로드 실패: {e}")
                
                if show_volatility:
                    is_dd = df_asset['Drawdown'] <= -10.0
                    # 연속 구간만 음영 (annotation_text 제거 → 라벨 겹침 해소)
                    dd_starts = df_asset.index[is_dd & ~is_dd.shift(1).fillna(False)]
                    dd_ends = df_asset.index[is_dd & ~is_dd.shift(-1).fillna(False)]
                    for idx, (s, e) in enumerate(zip(dd_starts, dd_ends)):
                        fig.add_vrect(
                            x0=s, x1=e,
                            fillcolor="rgba(255, 59, 48, 0.28)",
                            layer="below",
                            line_width=0,
                        )
                    # 최장 하락 구간에만 단일 라벨
                    if len(dd_starts):
                        lengths = [(e - s).days for s, e in zip(dd_starts, dd_ends)]
                        j = int(np.argmax(lengths))
                        fig.add_annotation(
                            x=dd_starts[j] + (dd_ends[j] - dd_starts[j]) / 2,
                            y=df_asset['Total_Value'].max(),
                            text="고변동성(MDD≤-10%)",
                            showarrow=False,
                            font=dict(size=11, color="#FF3B30"),
                            bgcolor="rgba(255,255,255,0.65)",
                        )
                
                fig.update_layout(
                    height=420,
                    margin=dict(l=60, r=55, t=30, b=20),
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                    yaxis=dict(
                        title="자산 (원)",
                        tickformat=",.0f",
                        separatethousands=True,
                        exponentformat="none",
                        showexponent="none",
                    ),
                    yaxis2=dict(
                        title="지수 (시작=100)",
                        overlaying="y",
                        side="right",
                        showgrid=False,
                    ),
                )
                # hover: 자산은 원, 지수는 그대로
                for tr in fig.data:
                    if tr.name and "시작=100" in str(tr.name):
                        tr.hovertemplate = "%{y:.1f}<extra>%{fullData.name}</extra>"
                    else:
                        tr.hovertemplate = "%{y:,.0f} 원<extra>%{fullData.name}</extra>"
                st.plotly_chart(fig, width="stretch")
                st.caption(
                    "✔️ 곡선은 **매일 종가 평가**, 종목 교체는 **매월 첫 거래일**. "
                    "코스피/코스닥은 **보조축·시작일=100** 지수화(절대 레벨 비교용 아님)."
                )
                
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
                            height=max(400, len(df_stock_ret) * 25),
                            margin=dict(l=20, r=40, t=30, b=20),
                            xaxis_title="누적 수익률 (%)",
                            yaxis_title="",
                        )
                        st.plotly_chart(fig_bar, width="stretch")
                    else:
                        st.info("편입된 종목이 없습니다.")

                with st.expander("📉 구간별 낙폭(Drawdown) 심층 분석", expanded=False):
                    fig_dd = go.Figure()
                    fig_dd.add_trace(go.Scatter(
                        x=df_asset.index, y=df_asset['Drawdown'],
                        fill='tozeroy', mode='lines', name='Drawdown',
                        line=dict(color='#FF4B4B', width=2)
                    ))
                    fig_dd.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=20), hovermode="x unified", yaxis_title="낙폭 (%)")
                    st.plotly_chart(fig_dd, width="stretch")
                    st.caption("✔️ 차트의 깊은 붉은 영역이 시스템이 수학적으로 찾아낸 계좌의 최대 스트레스(Drawdown) 구간입니다.")