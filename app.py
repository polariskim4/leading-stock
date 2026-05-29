import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="Leading Sector Analyzer", layout="wide")

# --- 1. 날짜 설정 (전년도 말 기준 YTD) ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title("📈 주도 섹터 및 눌림목 분석기")
st.info(f"분석 기간: {last_year_end} (전년 말) ~ {today_str} (현재)")

# --- 2. 데이터 유니버스 확보 (S&P 500, Nasdaq 100, Dow 30) ---
@st.cache_data(ttl=3600)
def get_clean_universe():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    def fetch_table(url, match_text):
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(io.StringIO(res.text), match=match_text)
        return tables[0]

    try:
        # S&P 500 종목 리스트 (Symbol이 있는 첫 번째 테이블만)
        sp500_df = fetch_table('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol')
        sym_col = 'Symbol' if 'Symbol' in sp500_df.columns else sp500_df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in sp500_df.columns else 'Sector'
        sector_map = sp500_df[[sym_col, sec_col]].rename(columns={sym_col: 'Ticker', sec_col: 'Sector'})

        # Nasdaq 100
        ndx_df = fetch_table('https://en.wikipedia.org/wiki/Nasdaq-100', 'Ticker')
        ndx_tickers = ndx_df['Ticker'].tolist()

        # Dow 30
        dow_df = fetch_table('https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average', 'Symbol')
        dow_tickers = dow_df['Symbol'].tolist()

        # 티커 세척: 숫자(연도) 제외, 공백 제거, 점(.)을 대시(-)로 변경
        combined = list(set(sector_map['Ticker'].tolist() + ndx_tickers + dow_tickers))
        clean_tickers = [str(t).strip().replace('.', '-') for t in combined 
                         if t and not str(t).isdigit() and len(str(t)) < 7]
        
        return sector_map, clean_tickers
    except Exception as e:
        st.error(f"유니버스 로드 중 오류 발생: {e}")
        return pd.DataFrame(), []

sector_info, tickers = get_clean_universe()

# --- 3. 가격 데이터 다운로드 (차단 방지 로직 적용) ---
@st.cache_data(ttl=3600)
def analyze_stocks(ticker_list):
    if not ticker_list:
        return pd.DataFrame()

    # 데이터 수집 기간
    start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    
    # yfinance 세션 설정 (Browser-like)
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    # 벌크 다운로드 시도
    with st.status("Yahoo Finance에서 데이터를 가져오는 중...", expanded=True) as status:
        try:
            # threads=True는 빠르지만 차단 위험이 큼. Rate limit 발생 시 False로 변경 권장.
            data = yf.download(ticker_list, start=start_date, end=today_str, 
                               interval="1wk", group_by='ticker', session=session, threads=True)
            status.update(label="데이터 다운로드 완료! 분석을 시작합니다.", state="complete")
        except Exception as e:
            st.error(f"다운로드 중 치명적 오류: {e}")
            return pd.DataFrame()

    final_data = []
    for ticker in ticker_list:
        try:
            # 멀티 인덱스 데이터 접근
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna()
            if len(df) < 50: continue

            price = df['Adj Close']
            current = price.iloc[-1]
            
            # YTD 수익률 계산 (안전한 인덱싱)
            ytd_subset = price.loc[last_year_end:]
            if ytd_subset.empty: continue
            ytd_return = ((current / ytd_subset.iloc[0]) - 1) * 100

            # 기술적 분석 (주봉 이평선)
            ma_series = price.rolling(window=100).mean() # 가장 긴 100일선 기준
            ma20 = price.rolling(20).mean().iloc[-1]
            ma50 = price.rolling(50).mean().iloc[-1]
            ma50_prev = price.rolling(50).mean().iloc[-5]
            ma100 = ma_series.iloc[-1]

            final_data.append({
                'Ticker': ticker,
                'YTD': ytd_return,
                'Price': current,
                'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                'MA50_UP': ma50 > ma50_prev,
                '1Y_High_Drop': ((current / price.tail(52).max()) - 1) * 100,
                '2Y_High_Drop': ((current / price.tail(104).max()) - 1) * 100,
                '3Y_High_Drop': ((current / price.tail(156).max()) - 1) * 100
            })
        except:
            continue
    return pd.DataFrame(final_data)

if tickers:
    analysis_df = analyze_stocks(tickers)
    
    if not analysis_df.empty:
        # 섹터 정보 결합
        result_df = pd.merge(analysis_df, sector_info, on='Ticker', how='left')
        result_df['Sector'] = result_df['Sector'].fillna('Etc/Unclassified')

        # 1. 주도 섹터 선별 (YTD 평균 기준)
        sector_perf = result_df.groupby('Sector')['YTD'].mean().sort_values(ascending=False)
        top_sector = sector_perf.index[0]

        st.success(f"🏆 현재 주도 섹터: **{top_sector}**")
        st.metric("평균 YTD 수익률", f"{sector_perf[0]:.2f}%")

        # 2. 상위 성과 종목
        st.subheader(f"🚀 {top_sector} 성과 상위 종목")
        top_3 = result_df[result_df['Sector'] == top_sector].sort_values('YTD', ascending=False).head(3)
        st.dataframe(top_3[['Ticker', 'YTD']].style.format({'YTD': '{:.2f}%'}))

        # 3. 눌림목 추천
        st.divider()
        st.subheader(f"🔍 {top_sector} 기술적 눌림목 추천")
        
        def check_signal(r):
            if not r['MA50_UP'] or r['Price'] < r['MA50'] * 0.95: return None
            # 우선순위: 100선 -> 50선 -> 20선 (3% 근접)
            for ma, name in zip([r['MA100'], r['MA50'], r['MA20']], ['100주선', '50주선', '20주선']):
                if abs(r['Price'] - ma) / ma < 0.03: return name
            return None

        leader_df = result_df[result_df['Sector'] == top_sector].copy()
        leader_df['Signal'] = leader_df.apply(check_signal, axis=1)
        recs = leader_df[leader_df['Signal'].notnull()].head(3)

        if not recs.empty:
            st.table(recs[['Ticker', 'YTD', '1Y_High_Drop', '2Y_High_Drop', '3Y_High_Drop', 'Signal']])
        else:
            st.info("현재 눌림목 조건에 맞는 우량 종목이 없습니다.")
    else:
        st.error("데이터 분석 결과가 없습니다. Yahoo Finance 차단이 지속되고 있을 수 있습니다. 잠시 후 다시 시도해주세요.")
