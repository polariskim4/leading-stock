import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="Leading Sector Analyzer", layout="wide")

# --- 1. 날짜 설정 (전년도 말 기준 YTD) ---
today = datetime.now()
# 로그에 찍힌 날짜를 고려하여, 현재 시점 기준 전년도 12월 31일을 잡습니다.
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title("📈 주도 섹터 및 눌림목 종목 분석기")
st.info(f"분석 기간: {last_year_end} ~ {today_str}")

# --- 2. 데이터 유니버스 확보 (S&P 500, Nasdaq 100, Dow 30) ---
@st.cache_data(ttl=3600)
def get_clean_universe():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    def fetch_table(url, match_text):
        res = requests.get(url, headers=headers)
        # 문자열에 match_text가 포함된 테이블만 가져와서 인덱스 오류 방지
        tables = pd.read_html(io.StringIO(res.text), match=match_text)
        return tables[0]

    try:
        # S&P 500 (Symbol 컬럼이 있는 테이블 매칭)
        sp500_df = fetch_table('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol')
        
        # 티커와 섹터 컬럼명 자동 탐색
        sym_col = 'Symbol' if 'Symbol' in sp500_df.columns else sp500_df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in sp500_df.columns else 'Sector'
        
        sector_map = sp500_df[[sym_col, sec_col]].rename(columns={sym_col: 'Ticker', sec_col: 'Sector'})

        # Nasdaq 100 (Ticker 컬럼이 있는 테이블)
        ndx_df = fetch_table('https://en.wikipedia.org/wiki/Nasdaq-100', 'Ticker')
        ndx_tickers = ndx_df['Ticker'].tolist()

        # Dow 30 (Symbol 컬럼이 있는 테이블)
        dow_df = fetch_table('https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average', 'Symbol')
        dow_tickers = dow_df['Symbol'].tolist()

        # 전체 합치기 및 티커 세척
        combined = list(set(sector_map['Ticker'].tolist() + ndx_tickers + dow_tickers))
        # 숫자로만 된 티커(연도 등) 제거 및 포맷 정리
        clean_tickers = [str(t).replace('.', '-') for t in combined if not str(t).isdigit()]
        
        return sector_map, clean_tickers
    except Exception as e:
        st.error(f"유니버스 로드 중 오류 발생: {e}")
        return pd.DataFrame(), []

sector_info, tickers = get_clean_universe()

# --- 3. 가격 데이터 벌크 다운로드 ---
@st.cache_data(ttl=3600)
def analyze_stocks(ticker_list):
    if not ticker_list:
        return pd.DataFrame()

    # 데이터 수집 기간 (이평선 계산을 위해 넉넉히 3년)
    start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    
    # threads=False로 설정하여 API 차단 가능성을 낮춤
    data = yf.download(ticker_list, start=start_date, end=today_str, interval="1wk", group_by='ticker', threads=True)
    
    final_data = []
    for ticker in ticker_list:
        try:
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna()
            if len(df) < 100: continue

            price = df['Adj Close']
            current = price.iloc[-1]
            
            # YTD 수익률
            ytd_price = price.loc[last_year_end:].iloc[0]
            ytd_return = ((current / ytd_price) - 1) * 100

            # 기술적 분석 (주봉 이평선)
            ma20 = price.rolling(20).mean().iloc[-1]
            ma50 = price.rolling(50).mean().iloc[-1]
            ma50_prev = price.rolling(50).mean().iloc[-5]
            ma100 = price.rolling(100).mean().iloc[-1]

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
    with st.spinner(f'{len(tickers)}개 종목의 데이터를 분석 중입니다...'):
        analysis_df = analyze_stocks(tickers)
        
        if not analysis_df.empty:
            # 섹터 정보 결합
            result_df = pd.merge(analysis_df, sector_info, on='Ticker', how='left')
            result_df['Sector'] = result_df['Sector'].fillna('Etc/Tech')

            # 1. 주도 섹터 선별
            sector_perf = result_df.groupby('Sector')['YTD'].mean().sort_values(ascending=False)
            top_sector = sector_perf.index[0]

            st.success(f"🏆 현재 주도 섹터: **{top_sector}** (평균 YTD: {sector_perf[0]:.2f}%)")

            # 2. 섹터 내 성과 상위 3개
            st.subheader(f"🚀 {top_sector} 내 수익률 TOP 3")
            top_3 = result_df[result_df['Sector'] == top_sector].sort_values('YTD', ascending=False).head(3)
            st.table(top_3[['Ticker', 'YTD']].rename(columns={'YTD': 'YTD 수익률(%)'}))

            # 3. 눌림목 추천
            st.divider()
            st.subheader(f"🔍 {top_sector} 내 눌림목(Buy) 추천 종목")
            
            def get_signal(r):
                # 50선 상승 중 + 50선 크게 이탈하지 않음
                if not r['MA50_UP'] or r['Price'] < r['MA50'] * 0.96: return None
                # 우선순위: 100선 -> 50선 -> 20선 근접도(3%)
                for ma, label in zip([r['MA100'], r['MA50'], r['MA20']], ['100주선', '50주선', '20주선']):
                    if abs(r['Price'] - ma) / ma < 0.03: return label
                return None

            leader_sector_df = result_df[result_df['Sector'] == top_sector].copy()
            leader_sector_df['Signal'] = leader_sector_df.apply(get_signal, axis=1)
            recs = leader_sector_df[leader_sector_df['Signal'].notnull()].head(3)

            if not recs.empty:
                st.dataframe(recs[['Ticker', 'YTD', '1Y_High_Drop', '2Y_High_Drop', '3Y_High_Drop', 'Signal']].style.format(precision=2))
            else:
                st.write("해당 섹터에 현재 기술적 눌림목 조건에 맞는 종목이 없습니다.")
        else:
            st.error("데이터 분석에 실패했습니다. Yahoo Finance 연결을 확인해주세요.")
