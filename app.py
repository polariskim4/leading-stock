import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="주식 섹터 분석기", layout="wide")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title(f"📈 시장 주도 섹터 및 눌림목 분석")
st.caption(f"기준: {last_year_end} 대비 현재 YTD 수익률")

# --- 2. 데이터 유니버스 확보 (S&P 500, Nasdaq 100, Dow 30) ---
@st.cache_data(ttl=3600)
def get_universe_data():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # S&P 500
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp500_res = requests.get(sp500_url, headers=headers)
        sp500_df = pd.read_html(io.StringIO(sp500_res.text))[0]
        
        # 컬럼명이 'Symbol'인지 'Ticker symbol'인지 확인 후 통일
        sym_col = 'Symbol' if 'Symbol' in sp500_df.columns else sp500_df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in sp500_df.columns else 'Sector'
        
        sector_map = sp500_df[[sym_col, sec_col]].rename(columns={sym_col: 'Ticker', sec_col: 'Sector'})

        # Nasdaq 100 & Dow 30 티커 추출 (구조적 유연성 확보)
        def get_tickers(url, table_idx):
            res = requests.get(url, headers=headers)
            tables = pd.read_html(io.StringIO(res.text))
            df = tables[table_idx]
            col = 'Ticker' if 'Ticker' in df.columns else ('Symbol' if 'Symbol' in df.columns else df.columns[0])
            return df[col].tolist()

        ndx_tickers = get_tickers('https://en.wikipedia.org/wiki/Nasdaq-100', 4)
        dow_tickers = get_tickers('https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average', 1)

        all_tickers = list(set(sector_map['Ticker'].tolist() + ndx_tickers + dow_tickers))
        all_tickers = [str(t).replace('.', '-') for t in all_tickers]
        
        return sector_map, all_tickers
    except Exception as e:
        st.error(f"유니버스 로드 실패: {e}")
        return pd.DataFrame(columns=['Ticker', 'Sector']), []

sector_df, tickers = get_universe_data()

# --- 3. 가격 데이터 분석 ---
@st.cache_data(ttl=3600)
def fetch_and_analyze(tickers_list):
    if not tickers_list: return pd.DataFrame()
    
    start_history = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    # 벌크 다운로드
    data = yf.download(tickers_list, start=start_history, end=today_str, interval="1wk", group_by='ticker', progress=False)
    
    results = []
    for ticker in tickers_list:
        try:
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna()
            if len(df) < 100: continue

            close = df['Adj Close']
            curr_price = close.iloc[-1]
            
            # YTD 수익률
            ytd_data = close.loc[last_year_end:]
            if ytd_data.empty: continue
            ytd_return = ((curr_price / ytd_data.iloc[0]) - 1) * 100

            # 이평선
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.rolling(50).mean().iloc[-1]
            ma50_prev = close.rolling(50).mean().iloc[-5]
            ma100 = close.rolling(100).mean().iloc[-1]

            results.append({
                'Ticker': ticker,
                'YTD_Return': ytd_return,
                'Curr_Price': curr_price,
                'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                'MA50_UP': ma50 > ma50_prev,
                'DD1Y': ((curr_price / close.tail(52).max()) - 1) * 100,
                'DD2Y': ((curr_price / close.tail(104).max()) - 1) * 100,
                'DD3Y': ((curr_price / close.tail(156).max()) - 1) * 100
            })
        except: continue
    return pd.DataFrame(results)

if tickers:
    with st.spinner('실시간 시장 분석 중...'):
        analysis_df = fetch_and_analyze(tickers)
        
        if not analysis_df.empty:
            # 안전한 병합: 두 DF 모두 'Ticker' 컬럼이 있는지 확인
            full_df = pd.merge(analysis_df, sector_df, on='Ticker', how='left')
            full_df['Sector'] = full_df['Sector'].fillna('Other Services')

            # 1. 주도 섹터
            sector_rank = full_df.groupby('Sector')['YTD_Return'].mean().sort_values(ascending=False)
            top_sector = sector_rank.index[0]

            st.success(f"🔥 현재 주도 섹터: **{top_sector}** (평균 YTD: {sector_rank[0]:.2f}%)")

            # 2. 섹터 내 TOP 3
            st.subheader(f"🚀 {top_sector} 성과 상위 종목")
            top_3 = full_df[full_df['Sector'] == top_sector].sort_values('YTD_Return', ascending=False).head(3)
            st.table(top_3[['Ticker', 'YTD_Return']].rename(columns={'YTD_Return': '수익률(%)'}))

            # 3. 눌림목 필터링
            st.divider()
            st.subheader(f"🔍 {top_sector} 눌림목 추천 (주봉 이평선 기준)")
            
            def identify_signal(row):
                if not row['MA50_UP'] or row['Curr_Price'] < row['MA50'] * 0.95: return None
                # 100 > 50 > 20 순서로 근접도(3%) 확인
                for ma, label in zip([row['MA100'], row['MA50'], row['MA20']], ['100주선', '50주선', '20주선']):
                    if abs(row['Curr_Price'] - ma) / ma < 0.03: return label
                return None

            leader_df = full_df[full_df['Sector'] == top_sector].copy()
            leader_df['Signal'] = leader_df.apply(identify_signal, axis=1)
            recs = leader_df[leader_df['Signal'].notnull()].head(3)

            if not recs.empty:
                st.dataframe(recs[['Ticker', 'YTD_Return', 'DD1Y', 'DD2Y', 'DD3Y', 'Signal']].style.format({
                    'YTD_Return': '{:.2f}%', 'DD1Y': '{:.2f}%', 'DD2Y': '{:.2f}%', 'DD3Y': '{:.2f}%'
                }))
            else:
                st.info("현재 기술적 눌림목 조건에 부합하는 우량 종목이 없습니다.")
        else:
            st.warning("분석 가능한 가격 데이터가 없습니다.")
