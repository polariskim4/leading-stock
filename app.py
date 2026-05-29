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

# UI 스타일 개선 (우측 정렬 및 컴팩트 레이아웃)
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 정확한 성과 및 눌림목 분석 (S&P500, Nasdaq100, Dow30)")

# --- 1. 날짜 설정 (정확한 YTD 기준) ---
today = datetime.now()
last_year_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. 데이터 소스 가져오기 함수들 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(io.StringIO(res.text))
        df = tables[0]
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
        df = pd.read_html(io.StringIO(res.text))[4] # 일반적으로 4번째 테이블
        ticker_col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
        tickers = df[ticker_col].str.replace('.', '-', regex=False).str.strip().tolist()
        return [t for t in tickers if not t.isdigit()]
    except: return []

@st.cache_data(ttl=86400)
def get_dow30_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text))[1] # 두 번째 테이블
        ticker_col = 'Symbol' if 'Symbol' in df.columns else df.columns[1]
        tickers = df[ticker_col].str.replace('.', '-', regex=False).str.strip().tolist()
        return [t for t in tickers if not t.isdigit()]
    except: return []

# 데이터 로드
sp500_data = get_sp500_list()

if not sp500_data.empty:
    # --- UI 사이드바 설정 ---
    # 기존 섹터 리스트에 Nasdaq100과 Dow30을 추가
    gics_sectors = sorted(sp500_data['GICS Sector'].unique().tolist())
    menu_options = gics_sectors + ["Nasdaq100", "Dow30"]
    
    selected_menu = st.sidebar.selectbox(
        "분석 대상(섹터/지수) 선택", 
        menu_options, 
        key="market_selector_unique"
    )
    
    # 선택된 메뉴에 따라 티커 리스트 결정
    if selected_menu == "Nasdaq100":
        target_tickers = get_nasdaq100_list()
    elif selected_menu == "Dow30":
        target_tickers = get_dow30_list()
    else:
        target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_menu]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상 종목: {len(target_tickers)}개")
    run_analysis = st.sidebar.button(f"{selected_menu} 분석 시작", key="run_button_unique")

    if run_analysis:
        analysis_results = []
        hist_start = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status(f"{selected_menu} 데이터 분석 중...", expanded=True) as status:
            chunk_size = 10
            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                try:
                    ytd_base_df = yf.download(chunk, start=last_year_start, end=last_year_end, 
                                             interval="1d", group_by='ticker', session=session, threads=False, progress=False)
                    w_data = yf.download(chunk, start=hist_start, end=today_str, 
                                        interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data.columns.levels[0]: continue
                            if ticker in ytd_base_df.columns.levels[0]:
                                t_base = ytd_base_df[ticker].dropna()
                                if t_base.empty: continue
                                base_price = t_base['Close'].iloc[-1]
                            else: continue

                            df = w_data[ticker].dropna()
                            if len(df) < 100: continue 

                            close = df['Close']
                            curr_p = close.iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100

                            ma20 = close.rolling(20).mean().iloc[-1]
                            ma50 = close.rolling(50).mean().iloc[-1]
                            ma100 = close.rolling(100).mean().iloc[-1]

                            # SMA 50 > 100 정배열 유지 종목만 필터
                            if not (ma50 > ma100): continue

                            dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                            dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                            
                            analysis_results.append({
                                'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                '1Y_고점대비': ((curr_p / close.tail(52).max()) - 1) * 100,
                                '2Y_고점대비': ((curr_p / close.tail(104).max()) - 1) * 100,
                                '3Y_고점대비': ((curr_p / close.tail(156).max()) - 1) * 100,
                                '인접도': min(dist_ma20, dist_ma50),
                                '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                            })
                        except: continue
                except: pass
                time.sleep(random.uniform(0.5, 0.8))
            status.update(label="분석 완료!", state="complete")

        if analysis_results:
            final_df = pd.DataFrame(analysis_results)
            
            st.subheader(f"🏆 {selected_menu} 올해 성과 상위 TOP 3")
            top_3 = final_df.sort_values('YTD', ascending=False).head(3)
            st.dataframe(
                top_3[['Ticker', '현재가', 'YTD']].style.format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )

            st.divider()
            st.subheader(f"🔍 {selected_menu} 눌림목 추천 TOP 5")
            recs = final_df.sort_values('인접도').head(5)
            st.dataframe(
                recs[['Ticker', '현재가', 'YTD', '1Y_고점대비', '2Y_고점대비', '3Y_고점대비', '인접SMA']].style
                .format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )
        else:
            st.warning("조건을 만족하는 종목을 찾지 못했습니다.")
else:
    st.warning("분석 대상을 불러오지 못했습니다.")
