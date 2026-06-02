import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="Market Alpha Hunter", layout="wide")

# UI 스타일 개선
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 거래량 기반 눌림목 추천")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. 데이터 소스 가져오기 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        df = df[~df['Symbol'].str.isnumeric()]
        return df[['Symbol', 'GICS Sector']]
    except: return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_nasdaq100_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Ticker')[0]
        ticker_col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
        tickers = df[ticker_col].astype(str).str.replace('.', '-', regex=False).str.strip().tolist()
        return [t for t in tickers if t and not t.isdigit() and t != 'nan']
    except: return []

@st.cache_data(ttl=86400)
def get_dow30_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        ticker_col = 'Symbol' if 'Symbol' in df.columns else df.columns[1]
        tickers = df[ticker_col].astype(str).str.replace('.', '-', regex=False).str.strip().tolist()
        return [t for t in tickers if t and not t.isdigit() and t != 'nan']
    except: return []

sp500_data = get_sp500_list()

if not sp500_data.empty:
    gics_sectors = sorted(sp500_data['GICS Sector'].unique().tolist())
    menu_options = gics_sectors + ["Nasdaq100", "Dow30"]
    selected_menu = st.sidebar.selectbox("분석 대상 선택", menu_options, key="market_selector")
    
    if selected_menu == "Nasdaq100":
        target_tickers = get_nasdaq100_list()
    elif selected_menu == "Dow30":
        target_tickers = get_dow30_list()
    else:
        target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_menu]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상: {len(target_tickers)}개 종목")
    run_analysis = st.sidebar.button(f"{selected_menu} 분석 시작")

    if run_analysis:
        performance_results = [] # 전체 성과 순위용
        recommendation_results = [] # 눌림목 필터용
        
        hist_start = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status(f"{selected_menu} 데이터 분석 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            status_text = st.empty()
            chunk_size = 15

            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                status_text.text(f"처리 중: {i}/{len(target_tickers)} 종목 완료")
                try:
                    ytd_base_df = yf.download(chunk, start=last_year_end_base if 'last_year_end_base' in locals() else last_year_start, 
                                             end=last_year_end, interval="1d", group_by='ticker', session=session, threads=False, progress=False)
                    w_data = yf.download(chunk, start=hist_start, end=today_str, 
                                        interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data.columns.levels[0] or ticker not in ytd_base_df.columns.levels[0]: continue
                            
                            t_base = ytd_base_df[ticker].dropna()
                            w_df = w_data[ticker].dropna()
                            if t_base.empty or len(w_df) < 100: continue

                            base_price = t_base['Close'].iloc[-1]
                            curr_p = w_df['Close'].iloc[-1]
                            curr_v = w_df['Volume'].iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100

                            # 1. 성과 순위 데이터 저장 (필터 없음)
                            performance_results.append({
                                'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret
                            })

                            # 2. 기술적 지표 계산 (눌림목 필터용)
                            ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                            ma50 = w_df['Close'].rolling(50).mean().iloc[-1]
                            ma100 = w_df['Close'].rolling(100).mean().iloc[-1]
                            max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                            vol_ratio = (curr_v / max_v_8w) if max_v_8w > 0 else 1.0

                            # 눌림목 필터 적용
                            if (ma50 > ma100) and (vol_ratio <= 0.65):
                                dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                                dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                                recommendation_results.append({
                                    'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                    '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                    '거래량비중(%)': vol_ratio * 100,
                                    '인접도': min(dist_ma20, dist_ma50),
                                    '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                                })
                        except: continue
                except: pass
                time.sleep(random.uniform(0.5, 0.8))
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))
            
            status_text.empty()
            progress_bar.empty()
            status.update(label="분석 완료!", state="complete")

        # --- 결과 출력 ---
        if performance_results:
            # 1. 섹터 전체 성과 상위 (YTD 기준)
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(performance_results)
            top_3 = perf_df.sort_values('YTD', ascending=False).head(3)
            st.dataframe(top_3.style.format(precision=1), hide_index=True, width="stretch")

            # 2. 눌림목 추천 종목
            st.divider()
            st.subheader(f"🔍 {selected_menu} 기술적 눌림목 추천 TOP 5")
            if recommendation_results:
                recs_df = pd.DataFrame(recommendation_results)
                recs = recs_df.sort_values('인접도').head(5)
                st.dataframe(recs[['Ticker', '현재가', 'YTD', '1Y_고점대비', '거래량비중(%)', '인접SMA']].style.format(precision=1), 
                             hide_index=True, width="stretch")
            else:
                st.info("현재 눌림목 조건(정배열 & 거래량 급감)을 만족하는 종목이 없습니다.")
        else:
            st.error("데이터를 불러오는 데 실패했습니다.")
