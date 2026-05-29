import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="주도 섹터 & 눌림목 분석기", layout="wide")

# --- 1. 날짜 설정 (전년도 말 기준 YTD) ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title(f"🚀 {today.year}년 시장 주도 섹터 및 눌림목 추천")
st.caption(f"분석 기준: {last_year_end} (전년 종가) 대비 현재 수익률")

# --- 2. 종목 및 섹터 데이터 로드 ---
@st.cache_data(ttl=3600)
def get_universe_data():
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        # S&P 500 및 섹터 정보
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        sp500_res = requests.get(sp500_url, headers=headers)
        sp500_df = pd.read_html(io.StringIO(sp500_res.text))[0]
        sector_map = sp500_df[['Symbol', 'GICS Sector']].rename(columns={'Symbol': 'Ticker', 'GICS Sector': 'Sector'})

        # Nasdaq 100 & Dow 30 추가 (섹터는 S&P500 기준 활용)
        ndx_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        ndx_res = requests.get(ndx_url, headers=headers)
        ndx_tickers = pd.read_html(io.StringIO(ndx_res.text))[4]['Ticker'].tolist()

        dow_url = 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average'
        dow_res = requests.get(dow_url, headers=headers)
        dow_tickers = pd.read_html(io.StringIO(dow_res.text))[1]['Symbol'].tolist()

        all_tickers = list(set(sector_map['Ticker'].tolist() + ndx_tickers + dow_tickers))
        all_tickers = [t.replace('.', '-') for t in all_tickers]
        
        return sector_map, all_tickers
    except Exception as e:
        st.error(f"데이터 로드 에러: {e}")
        return pd.DataFrame(), []

sector_df, tickers = get_universe_data()

# --- 3. 가격 데이터 벌크 다운로드 및 분석 ---
@st.cache_data(ttl=3600)
def fetch_and_analyze(tickers_list):
    # 주봉 데이터 수집 (MA 및 MDD 계산을 위해 3년치)
    start_history = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    data = yf.download(tickers_list, start=start_history, end=today_str, interval="1wk", group_by='ticker')
    
    analysis_results = []
    
    for ticker in tickers_list:
        try:
            # 개별 종목 주가 추출
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna()
            if len(df) < 100: continue

            curr_price = df['Adj Close'].iloc[-1]
            # YTD 계산: 올해 첫 데이터 대비 현재가
            ytd_start_price = df.loc[last_year_end:].iloc[0]['Adj Close']
            ytd_return = ((curr_price / ytd_start_price) - 1) * 100

            # 기술적 지표 (주봉 이평선)
            ma20 = df['Adj Close'].rolling(20).mean().iloc[-1]
            ma50 = df['Adj Close'].rolling(50).mean().iloc[-1]
            ma50_prev = df['Adj Close'].rolling(50).mean().iloc[-5]
            ma100 = df['Adj Close'].rolling(100).mean().iloc[-1]

            # 고점 대비 하락률 (MDD)
            def get_drawdown(years):
                peak = df['Adj Close'].tail(years * 52).max()
                return ((curr_price / peak) - 1) * 100

            analysis_results.append({
                'Ticker': ticker,
                'YTD_Return': ytd_return,
                'Curr_Price': curr_price,
                'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                'MA50_UP': ma50 > ma50_prev, # 50일선 상승 여부
                'DD1Y': get_drawdown(1),
                'DD2Y': get_drawdown(2),
                'DD3Y': get_drawdown(3)
            })
        except: continue
        
    return pd.DataFrame(analysis_results)

if tickers:
    with st.spinner('시장을 분석 중입니다... 약 30초 소요됩니다.'):
        raw_analysis = fetch_and_analyze(tickers)
        # 섹터 정보 결합
        full_df = pd.merge(raw_analysis, sector_df, on='Ticker', how='left')
        full_df['Sector'] = full_df['Sector'].fillna('Technology/Others')

        # 1. 주도 섹터 선정
        sector_rank = full_df.groupby('Sector')['YTD_Return'].mean().sort_values(ascending=False)
        leading_sector = sector_rank.index[0]

        col1, col2 = st.columns(2)
        with col1:
            st.success(f"🏆 현재 주도 섹터: **{leading_sector}**")
            st.write(f"평균 YTD 수익률: {sector_rank[0]:.2f}%")
        
        # 2. 주도 섹터 내 상위 3개 종목
        top_3 = full_df[full_df['Sector'] == leading_sector].sort_values('YTD_Return', ascending=False).head(3)
        with col2:
            st.write("### 섹터 내 성과 TOP 3")
            st.table(top_3[['Ticker', 'YTD_Return']].style.format({'YTD_Return': '{:.2f}%'}))

        # 3. 눌림목 추천 종목 (기술적 필터링)
        st.divider()
        st.subheader(f"🔍 {leading_sector} 섹터 내 눌림목 추천")
        
        # 필터링 조건 적용
        # 1) 50주선 정배열(상승 중)
        # 2) 현재가가 50주선보다 위에 있음 (크게 이탈하지 않음)
        # 3) 100주선 > 50주선 > 20주선 순서로 근접(±3%) 확인
        leader_df = full_df[full_df['Sector'] == leading_sector]
        
        def check_rebound(row):
            if not row['MA50_UP']: return None
            if row['Curr_Price'] < row['MA50'] * 0.95: return None # 50주선 하방 이탈 제외
            
            # 이격도 체크
            for ma, name in zip([row['MA100'], row['MA50'], row['MA20']], ['100주선', '50주선', '20주선']):
                if abs(row['Curr_Price'] - ma) / ma < 0.03:
                    return name
            return None

        leader_df['Signal'] = leader_df.apply(check_rebound, axis=1)
        recommendations = leader_df[leader_df['Signal'].notnull()].head(3)

        if not recommendations.empty:
            display_cols = ['Ticker', 'YTD_Return', 'DD1Y', 'DD2Y', 'DD3Y', 'Signal']
            st.dataframe(recommendations[display_cols].rename(columns={
                'YTD_Return': 'YTD 수익률',
                'DD1Y': '1년 고점대비',
                'DD2Y': '2년 고점대비',
                'DD3Y': '3년 고점대비',
                'Signal': '눌림 지점'
            }).style.format({
                'YTD 수익률': '{:.2f}%',
                '1년 고점대비': '{:.2f}%',
                '2년 고점대비': '{:.2f}%',
                '3년 고점대비': '{:.2f}%'
            }), use_container_width=True)
        else:
            st.info("현재 기술적 눌림목 조건에 부합하는 종목이 없습니다.")

st.sidebar.info("💡 **Tip**: 주봉 기준 이동평균선은 중장기 추세를 나타냅니다. 50주 이격도가 낮은 종목은 건강한 조정 구간일 확률이 높습니다.")
