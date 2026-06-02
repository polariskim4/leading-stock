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

# UI 스타일 개선 (CSS)
st.markdown("""
    <style>
    .main { font-size: 0.9rem; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 거래량 기반 눌림목 추천")

# --- 1. 날짜 설정 (안정화) ---
@st.cache_data
def get_dates():
    today = datetime.now()
    # YTD 계산을 위한 작년 말 종가 기준일
    last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
    start_date = (today - timedelta(days=500)).strftime('%Y-%m-%d')
    return today.strftime('%Y-%m-%d'), last_year_end, start_date

today_str, last_year_end, start_date = get_dates()

# --- 2. 데이터 소스 가져오기 (캐싱 최적화) ---
@st.cache_data(ttl=86400)
def get_ticker_list(market_type):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        if market_type == "S&P 500":
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            res = requests.get(url, headers=headers, timeout=10)
            df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
            df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False)
            return df[['Symbol', 'GICS Sector']]
        elif market_type == "Nasdaq100":
            url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            res = requests.get(url, headers=headers, timeout=10)
            df = pd.read_html(io.StringIO(res.text), match='Ticker')[0]
            col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
            return df[[col]].rename(columns={col: 'Symbol'})
    except Exception as e:
        st.error(f"목록 로드 실패: {e}")
        return pd.DataFrame()

# --- 3. 핵심 분석 함수 ---
def analyze_stocks(tickers, last_year_end):
    performance_results = []
    recommendation_results = []
    
    # 세션 설정으로 속도 및 안정성 향상
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})

    # 데이터 한꺼번에 다운로드 (속도 향상)
    data = yf.download(tickers, start=last_year_end, interval="1d", session=session, group_by='ticker', progress=False)
    
    for ticker in tickers:
        try:
            df = data[ticker].dropna()
            if len(df) < 100: continue

            # 지표 계산
            curr_p = df['Close'].iloc[-1]
            base_p = df['Close'].iloc[0] # 작년 말 종가 근사치
            ytd_ret = ((curr_p / base_p) - 1) * 100
            
            ma20 = df['Close'].rolling(20).mean()
            ma50 = df['Close'].rolling(50).mean()
            ma100 = df['Close'].rolling(100).mean()
            
            # 눌림목 로직 개선
            # 1. 정배열 (50 > 100)
            # 2. 거래량 급감 (최근 1주 평균 거래량이 직전 4주 평균의 65% 이하)
            vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
            vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
            vol_ratio = vol_ma5 / vol_ma20 if vol_ma20 > 0 else 1.0
            
            performance_results.append({'Ticker': ticker, 'Price': curr_p, 'YTD (%)': ytd_ret})

            # 전략: 정배열 상태에서 가격이 20일선이나 50일선에 근접할 때 (눌림)
            if ma50.iloc[-1] > ma100.iloc[-1] and vol_ratio <= 0.70:
                dist_ma20 = abs(curr_p - ma20.iloc[-1]) / ma20.iloc[-1] * 100
                dist_ma50 = abs(curr_p - ma50.iloc[-1]) / ma50.iloc[-1] * 100
                
                if dist_ma20 < 3 or dist_ma50 < 3: # 이평선 3% 이내 근접 시
                    recommendation_results.append({
                        'Ticker': ticker,
                        'YTD (%)': ytd_ret,
                        'Price': curr_p,
                        'Vol Ratio': vol_ratio,
                        'Nearest MA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50',
                        'Dist (%)': min(dist_ma20, dist_ma50)
                    })
        except:
            continue
            
    return pd.DataFrame(performance_results), pd.DataFrame(recommendation_results)

# --- 4. 메인 UI ---
sp500_raw = get_ticker_list("S&P 500")
if not sp500_raw.empty:
    sectors = sorted(sp500_raw['GICS Sector'].unique().tolist())
    selected_menu = st.sidebar.selectbox("분석 대상 선택", ["S&P 500 전체"] + sectors + ["Nasdaq100"])
    
    if selected_menu == "S&P 500 전체":
        target_tickers = sp500_raw['Symbol'].tolist()
    elif selected_menu == "Nasdaq100":
        target_tickers = get_ticker_list("Nasdaq100")['Symbol'].tolist()
    else:
        target_tickers = sp500_raw[sp500_raw['GICS Sector'] == selected_menu]['Symbol'].tolist()

    if st.sidebar.button("분석 실행"):
        with st.spinner(f"{selected_menu} 분석 중..."):
            perf_df, rec_df = analyze_stocks(target_tickers, last_year_end)
            
            if not perf_df.empty:
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("🔥 YTD 성과 상위 TOP 5")
                    st.table(perf_df.sort_values('YTD (%)', ascending=False).head(5))
                
                st.divider()
                st.subheader("🎯 기술적 눌림목 추천 (정배열 & 거래량 급감)")
                if not rec_df.empty:
                    st.dataframe(rec_df.sort_values('Dist (%)').style.format({
                        'YTD (%)': '{:.2f}', 'Price': '{:.2f}', 'Vol Ratio': '{:.2f}', 'Dist (%)': '{:.2f}'
                    }), use_container_width=True)
                else:
                    st.info("조건을 만족하는 눌림목 종목이 없습니다.")
