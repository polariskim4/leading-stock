import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="Leading Sector Buy-the-Dip", layout="wide")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title("📈 주도 섹터 및 눌림목 추천 분석기")
st.caption(f"분석 기간: {last_year_end} (전년 말) ~ {today_str} (현재)")

# --- 2. 종목 유니버스 수집 (안정성 강화) ---
@st.cache_data(ttl=3600)
def get_verified_universe():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    
    try:
        # S&P 500 (Symbol 컬럼이 명시된 테이블만)
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(io.StringIO(res.text), match='Symbol')
        sp500_df = tables[0]
        
        sym_col = 'Symbol' if 'Symbol' in sp500_df.columns else sp500_df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in sp500_df.columns else 'Sector'
        
        sector_map = sp500_df[[sym_col, sec_col]].rename(columns={sym_col: 'Ticker', sec_col: 'Sector'})
        
        # 티커 정제: 숫자 제거, 길이 제한, 점(.)을 대시(-)로 변경
        valid_tickers = [str(t).strip().replace('.', '-') for t in sector_map['Ticker'].tolist() 
                         if t and not str(t).isdigit() and len(str(t)) <= 5]
        
        return sector_map, valid_tickers
    except Exception as e:
        st.error(f"유니버스 로드 실패: {e}")
        return pd.DataFrame(), []

sector_info, tickers = get_verified_universe()

# --- 3. 분할 다운로드 및 분석 로직 ---
@st.cache_data(ttl=3600)
def fetch_data_in_chunks(ticker_list):
    if not ticker_list: return pd.DataFrame()

    start_history = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    chunk_size = 50 # 한 번에 50개씩 요청하여 차단 방지
    all_results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i in range(0, len(ticker_list), chunk_size):
        chunk = ticker_list[i:i + chunk_size]
        status_text.text(f"데이터 수집 중: {i}/{len(ticker_list)} 종목 완료...")
        
        try:
            # 개별 청크 다운로드
            data = yf.download(chunk, start=start_history, end=today_str, 
                               interval="1wk", group_by='ticker', threads=False, progress=False)
            
            for ticker in chunk:
                try:
                    # 종목별 데이터 추출 및 검증
                    if ticker not in data.columns.levels[0]: continue
                    df = data[ticker].dropna()
                    if len(df) < 52: continue # 최소 1년치 데이터 필요

                    price = df['Adj Close']
                    curr = price.iloc[-1]
                    
                    # YTD 계산
                    ytd_start = price.loc[last_year_end:].iloc[0]
                    ytd_ret = ((curr / ytd_start) - 1) * 100
                    
                    # 이평선 계산 (주봉)
                    ma20 = price.rolling(20).mean().iloc[-1]
                    ma50 = price.rolling(50).mean().iloc[-1]
                    ma50_prev = price.rolling(50).mean().iloc[-5]
                    ma100 = price.rolling(100).mean().iloc[-1]
                    
                    all_results.append({
                        'Ticker': ticker, 'YTD': ytd_ret, 'Price': curr,
                        'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                        'MA50_UP': ma50 > ma50_prev,
                        'DD1Y': ((curr / price.tail(52).max()) - 1) * 100,
                        'DD2Y': ((curr / price.tail(104).max()) - 1) * 100,
                        'DD3Y': ((curr / price.tail(156).max()) - 1) * 100
                    })
                except: continue
        except:
            st.warning(f"청크 {i//chunk_size + 1} 다운로드 중 오류 발생. 건너뜁니다.")
        
        progress_bar.progress(min((i + chunk_size) / len(ticker_list), 1.0))
        time.sleep(1) # Yahoo 서버 부하 경감
    
    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(all_results)

if tickers:
    with st.spinner('시장 데이터를 정밀 분석 중입니다...'):
        analysis_df = fetch_data_in_chunks(tickers)
        
        if not analysis_df.empty:
            # 섹터 결합
            full_df = pd.merge(analysis_df, sector_info, on='Ticker', how='left')
            full_df['Sector'] = full_df['Sector'].fillna('기타/기술')

            # 1. 주도 섹터 선정
            sector_perf = full_df.groupby('Sector')['YTD'].mean().sort_values(ascending=False)
            top_sector = sector_perf.index[0]

            st.success(f"🏆 현재 주도 섹터: **{top_sector}**")
            st.metric("평균 YTD 수익률", f"{sector_perf[0]:.2f}%")

            # 2. 섹터 내 TOP 3 종목
            st.subheader(f"🚀 {top_sector} 성과 상위 종목")
            top_3 = full_df[full_df['Sector'] == top_sector].sort_values('YTD', ascending=False).head(3)
            st.dataframe(top_3[['Ticker', 'YTD']].style.format({'YTD': '{:.2f}%'}))

            # 3. 눌림목 추천
            st.divider()
            st.subheader(f"🔍 {top_sector} 기술적 눌림목 추천")
            
            def check_buy_signal(row):
                # 50선 상승 중 + 현재가가 50선 위에 위치
                if not row['MA50_UP'] or row['Price'] < row['MA50'] * 0.97: return None
                # 이평선 근접도(3%) 체크: 100 > 50 > 20 순서
                for ma, label in zip([row['MA100'], row['MA50'], row['MA20']], ['100주선', '50주선', '20주선']):
                    if abs(row['Price'] - ma) / ma < 0.03: return label
                return None

            leader_df = full_df[full_df['Sector'] == top_sector].copy()
            leader_df['Signal'] = leader_df.apply(check_buy_signal, axis=1)
            recs = leader_df[leader_df['Signal'].notnull()].head(3)

            if not recs.empty:
                st.table(recs[['Ticker', 'YTD', 'DD1Y', 'DD2Y', 'DD3Y', 'Signal']])
            else:
                st.info("현재 눌림목 조건에 맞는 종목이 없습니다.")
        else:
            st.error("데이터 분석에 실패했습니다. Yahoo Finance의 차단이 강합니다. 분석 범위를 줄이거나 나중에 다시 시도해 주세요.")
