import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import requests

# 페이지 설정
st.set_page_config(page_title="실시간 주도 섹터 및 눌림목 분석", layout="wide")

# --- 1. 동적 날짜 설정 ---
today = datetime.now()
current_year = today.year
# YTD 계산을 위한 기준일: 전년도 12월 31일
last_year_end = datetime(current_year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title(f"📊 {current_year}년 주도 섹터 및 눌림목 추천")
st.caption(f"기준 기간: {last_year_end} ~ {today_str} (YTD 분석)")

# --- 2. 유니버스 데이터 가져오기 (S&P500, Nasdaq100, Dow30) ---
@st.cache_data(ttl=3600)
def get_stock_universe():
    try:
        # 위키피디아 차단을 피하기 위한 헤더 설정
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        
        # S&P 500 & Sectors
        sp500 = pd.read_html(requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers).text)[0]
        sp500_df = sp500[['Symbol', 'GICS Sector']].rename(columns={'Symbol': 'Ticker', 'GICS Sector': 'Sector'})
        
        # Nasdaq 100 & Dow 30 (섹터 정보는 S&P500과 병합하여 활용)
        ndx_tickers = pd.read_html(requests.get('https://en.wikipedia.org/wiki/Nasdaq-100', headers=headers).text)[4]['Ticker'].tolist()
        dow_tickers = pd.read_html(requests.get('https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average', headers=headers).text)[1]['Symbol'].tolist()
        
        all_tickers = list(set(sp500_df['Ticker'].tolist() + ndx_tickers + dow_tickers))
        all_tickers = [t.replace('.', '-') for t in all_tickers]
        
        return sp500_df, all_tickers
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), []

sp500_info, all_tickers = get_stock_universe()

# --- 3. 데이터 분석 로직 ---
@st.cache_data(ttl=3600)
def analyze_market(tickers, start_date, end_date):
    # 주봉 데이터 및 MDD 계산을 위해 3년치 데이터 수집
    data_start = (datetime.strptime(start_date, '%Y-%m-%d') - timedelta(weeks=160)).strftime('%Y-%m-%d')
    raw_data = yf.download(tickers, start=data_start, end=end_date, interval="1wk")['Adj Close']
    
    # YTD 수익률 계산
    # 전년도 말(또는 올해 초 첫 데이터) 대비 현재가
    ytd_returns = ((raw_data.iloc[-1] / raw_data.loc[start_date:].iloc[0]) - 1) * 100
    return raw_data, ytd_returns

if all_tickers:
    with st.spinner('실시간 시장 데이터를 분석 중입니다...'):
        price_data, ytd_series = analyze_market(all_tickers, last_year_end, today_str)
        
        df_analysis = pd.DataFrame(ytd_series).rename(columns={0: 'YTD_Return'})
        df_analysis = df_analysis.merge(sp500_info, left_index=True, right_on='Ticker', how='left')
        df_analysis['Sector'] = df_analysis['Sector'].fillna('Others')

        # 4. 주도 섹터 선별
        sector_perf = df_analysis.groupby('Sector')['YTD_Return'].mean().sort_values(ascending=False)
        leading_sector = sector_perf.index[0]

        c1, c2 = st.columns([1, 1])
        with c1:
            st.success(f"🔥 현재 주도 섹터: **{leading_sector}**")
            st.metric("섹터 평균 수익률(YTD)", f"{sector_perf[0]:.2f}%")
        
        with c2:
            st.write(f"### {leading_sector} 성과 상위 종목")
            top_3 = df_analysis[df_analysis['Sector'] == leading_sector].sort_values('YTD_Return', ascending=False).head(3)
            st.table(top_3[['Ticker', 'YTD_Return']].style.format({'YTD_Return': '{:.2f}%'}))

        # 5. 기술적 분석 기반 추천 (눌림목)
        st.divider()
        st.subheader(f"🔍 {leading_sector} 내 눌림목 추천 종목 (Technical Buy)")
        
        leader_tickers = df_analysis[df_analysis['Sector'] == leading_sector]['Ticker'].tolist()
        recommendations = []

        for ticker in leader_tickers:
            if ticker not in price_data.columns: continue
            
            series = price_data[ticker].dropna()
            if len(series) < 100: continue
            
            # 이동평균선 (주봉)
            ma20 = series.rolling(20).mean()
            ma50 = series.rolling(50).mean()
            ma100 = series.rolling(100).mean()
            
            curr = series.iloc[-1]
            
            # 조건 1: 50주선이 정배열/상승세 (추세 살아있음)
            is_ma50_up = ma50.iloc[-1] > ma50.iloc[-5]
            
            # 조건 2: 50주선을 크게 이탈하지 않음 (이격도 95% 이상)
            not_broken = curr > (ma50.iloc[-1] * 0.95)
            
            # 조건 3: 눌림목 판정 (100선 > 50선 > 20선 우선순위로 근접도 3% 이내)
            on_ma100 = abs(curr - ma100.iloc[-1]) / ma100.iloc[-1] < 0.03
            on_ma50 = abs(curr - ma50.iloc[-1]) / ma50.iloc[-1] < 0.03
            on_ma20 = abs(curr - ma20.iloc[-1]) / ma20.iloc[-1] < 0.03
            
            if is_ma50_up and not_broken and (on_ma100 or on_ma50 or on_ma20):
                # MDD 계산
                def get_mdd(years):
                    peak = series.tail(int(52 * years)).max()
                    return ((curr / peak) - 1) * 100

                recommendations.append({
                    'Ticker': ticker,
                    'YTD': f"{df_analysis.loc[df_analysis['Ticker']==ticker, 'YTD_Return'].values[0]:.2f}%",
                    '1Y 고점대비': f"{get_mdd(1):.2f}%",
                    '2Y 고점대비': f"{get_mdd(2):.2f}%",
                    '3Y 고점대비': f"{get_mdd(3):.2f}%",
                    '신호': '100주선 근접' if on_ma100 else ('50주선 근접' if on_ma50 else '20주선 근접')
                })
            
            if len(recommendations) >= 3: break

        if recommendations:
            st.dataframe(pd.DataFrame(recommendations), use_container_width=True)
        else:
            st.info("현재 기술적 눌림목 조건을 만족하는 종목이 없습니다.")

# --- 사이드바 설명 ---
st.sidebar.header("분석 가이드라인")
st.sidebar.write(f"""
- **기준일**: {last_year_end} 종가 대비 현재가
- **분석 대상**: S&P500, NDX100, DJI30
- **이평선 기준**: 주봉(Weekly) 데이터 사용
- **눌림목 우선순위**: 100주선 > 50주선 > 20주선 근접 여부
""")
