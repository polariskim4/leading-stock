import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Sector Dip-Buyer", layout="wide")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title("📈 S&P 500 주도 섹터 및 눌림목 분석")
st.caption(f"Yahoo Finance 차단 방지 모드 작동 중 | 분석 기준일: {last_year_end}")

# --- 2. S&P 500 유니버스 정밀 수집 ---
@st.cache_data(ttl=3600)
def get_sp500_clean():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        # 'Symbol' 문자열이 포함된 테이블만 정확히 추출
        tables = pd.read_html(io.StringIO(res.text), match='Symbol')
        df = tables[0]
        
        # 컬럼명 추출
        sym_col = 'Symbol' if 'Symbol' in df.columns else df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in df.columns else 'Sector'
        
        # 데이터 정제: 숫자(연도) 티커 완전 제거 및 형식 통일
        sector_map = {}
        for _, row in df.iterrows():
            ticker = str(row[sym_col]).strip().replace('.', '-')
            if ticker.isdigit() or len(ticker) > 6: # 숫자로만 된 연도 데이터 필터링
                continue
            sector_map[ticker] = row[sec_col]
            
        return sector_map, list(sector_map.keys())
    except Exception as e:
        st.error(f"유니버스 로드 실패: {e}")
        return {}, []

sector_dict, tickers = get_sp500_clean()

# --- 3. 차단 방지형 분할 다운로드 로직 ---
@st.cache_data(ttl=3600)
def fetch_data_safely(ticker_list):
    if not ticker_list: return pd.DataFrame()

    start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    
    # 세션 설정
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'})
    
    chunk_size = 25  # 한 번에 25개씩만 요청 (차단 위험 낮춤)
    all_results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(0, len(ticker_list), chunk_size):
        chunk = ticker_list[i : i + chunk_size]
        status_text.text(f"데이터 수집 중: {i}/{len(ticker_list)} 완료 (차단 방지를 위해 천천히 읽는 중...)")
        
        try:
            # threads=False로 설정하여 순차적 요청 (서버 부하 경감 핵심)
            data = yf.download(chunk, start=start_date, end=today_str, 
                               interval="1wk", group_by='ticker', 
                               session=session, threads=False, progress=False)
            
            for ticker in chunk:
                try:
                    if ticker not in data.columns.levels[0]: continue
                    df = data[ticker].dropna()
                    if len(df) < 52: continue

                    close = df['Adj Close']
                    curr = close.iloc[-1]
                    ytd_start = close.loc[last_year_end:].iloc[0]
                    ytd_ret = ((curr / ytd_start) - 1) * 100

                    # 기술적 지표
                    ma20 = close.rolling(20).mean().iloc[-1]
                    ma50 = close.rolling(50).mean().iloc[-1]
                    ma50_prev = close.rolling(50).mean().iloc[-5]
                    ma100 = close.rolling(100).mean().iloc[-1]

                    all_results.append({
                        'Ticker': ticker, 'YTD': ytd_ret, 'Price': curr,
                        'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                        'MA50_UP': ma50 > ma50_prev,
                        'DD1Y': ((curr / close.tail(52).max()) - 1) * 100,
                        'DD2Y': ((curr / close.tail(104).max()) - 1) * 100,
                        'DD3Y': ((curr / close.tail(156).max()) - 1) * 100
                    })
                except: continue
        except Exception as e:
            st.warning(f"청크 다운로드 중 오류 발생(일부 종목 건너뜀): {e}")
            
        # 요청 간 휴식 시간 (차단 회피 핵심)
        time.sleep(2)
        progress_bar.progress(min((i + chunk_size) / len(ticker_list), 1.0))
        
    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(all_results)

if tickers:
    with st.spinner('S&P 500 데이터를 정밀 분석 중입니다...'):
        analysis_df = fetch_data_safely(tickers)
        
        if not analysis_df.empty:
            analysis_df['Sector'] = analysis_df['Ticker'].map(sector_dict)
            
            # 1. 주도 섹터
            sector_perf = analysis_df.groupby('Sector')['YTD'].mean().sort_values(ascending=False)
            top_sector = sector_perf.index[0]

            st.success(f"🏆 주도 섹터: **{top_sector}** (평균 YTD: {sector_perf[0]:.2f}%)")

            # 2. TOP 3 종목
            st.subheader(f"🚀 {top_sector} 성과 상위 종목")
            top_3 = analysis_df[analysis_df['Sector'] == top_sector].sort_values('YTD', ascending=False).head(3)
            st.table(top_3[['Ticker', 'YTD']].rename(columns={'YTD': '수익률(%)'}))

            # 3. 눌림목 추천
            st.divider()
            st.subheader(f"🔍 {top_sector} 기술적 눌림목 추천")
            
            def get_signal(r):
                if not r['MA50_UP'] or r['Price'] < r['MA50'] * 0.96: return None
                for ma, label in zip([r['MA100'], r['MA50'], r['MA20']], ['100주선', '50주선', '20주선']):
                    if abs(r['Price'] - ma) / ma < 0.03: return label
                return None

            leader_df = analysis_df[analysis_df['Sector'] == top_sector].copy()
            leader_df['Signal'] = leader_df.apply(get_signal, axis=1)
            recs = leader_df[leader_df['Signal'].notnull()].head(3)

            if not recs.empty:
                st.dataframe(recs[['Ticker', 'YTD', 'DD1Y', 'DD2Y', 'DD3Y', 'Signal']].style.format(precision=2))
            else:
                st.info("조건에 맞는 눌림목 종목이 현재 섹터에 없습니다.")
        else:
            st.error("데이터 분석 실패. Yahoo Finance 서버가 응답하지 않습니다. 분석 범위를 더 줄이거나 나중에 시도해 주세요.")
