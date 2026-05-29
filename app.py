import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Leading Sector Analyzer", layout="wide")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title("📈 S&P 500 주도 섹터 및 눌림목 분석")
st.info(f"분석 대상: S&P 500 지수 종목 | 기간: {last_year_end} ~ {today_str}")

# --- 2. S&P 500 유니버스 수집 (정밀 세척) ---
@st.cache_data(ttl=3600)
def get_sp500_universe():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # 'Symbol' 문구가 포함된 테이블만 정확히 타겟팅
        tables = pd.read_html(io.StringIO(response.text), match='Symbol')
        df = tables[0]
        
        # 컬럼명 유연하게 대응
        sym_col = 'Symbol' if 'Symbol' in df.columns else df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in df.columns else 'Sector'
        
        # 티커 세척: 숫자로만 된 데이터(연도 등) 제거 및 특수문자 처리
        cleaned_list = []
        sector_mapping = {}
        
        for _, row in df.iterrows():
            ticker = str(row[sym_col]).strip().replace('.', '-')
            # 숫자로만 구성되었거나 너무 긴 티커 제외
            if ticker.isdigit() or len(ticker) > 6:
                continue
            cleaned_list.append(ticker)
            sector_mapping[ticker] = row[sec_col]
            
        return sector_mapping, cleaned_list
    except Exception as e:
        st.error(f"S&P 500 리스트 로드 실패: {e}")
        return {}, []

sector_dict, tickers = get_sp500_universe()

# --- 3. 가격 데이터 분석 (차단 방지 최적화) ---
@st.cache_data(ttl=3600)
def analyze_market(ticker_list):
    if not ticker_list: return pd.DataFrame()

    # 데이터 수집 (MA 및 MDD 계산을 위해 3년치 데이터)
    start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
    
    # 세션 설정을 통해 브라우저처럼 위장
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    })

    with st.status("Yahoo Finance 데이터 수집 중...", expanded=True) as status:
        try:
            # 병렬 처리를 끄고(threads=False) 세션을 사용하여 안정성 확보
            data = yf.download(ticker_list, start=start_date, end=today_str, 
                               interval="1wk", group_by='ticker', 
                               session=session, threads=False, progress=True)
            status.update(label="데이터 다운로드 완료!", state="complete")
        except Exception as e:
            st.error(f"데이터 수집 실패: {e}")
            return pd.DataFrame()

    results = []
    for ticker in ticker_list:
        try:
            if ticker not in data.columns.levels[0]: continue
            df = data[ticker].dropna()
            if len(df) < 50: continue

            close = df['Adj Close']
            curr = close.iloc[-1]
            
            # YTD 계산
            ytd_data = close.loc[last_year_end:]
            if ytd_data.empty: continue
            ytd_ret = ((curr / ytd_data.iloc[0]) - 1) * 100

            # 이평선
            ma20 = close.rolling(20).mean().iloc[-1]
            ma50 = close.rolling(50).mean().iloc[-1]
            ma50_prev = close.rolling(50).mean().iloc[-5]
            ma100 = close.rolling(100).mean().iloc[-1]

            results.append({
                'Ticker': ticker, 'YTD': ytd_ret, 'Price': curr,
                'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                'MA50_UP': ma50 > ma50_prev,
                '1Y_High_Drop': ((curr / close.tail(52).max()) - 1) * 100,
                '2Y_High_Drop': ((curr / close.tail(104).max()) - 1) * 100,
                '3Y_High_Drop': ((curr / close.tail(156).max()) - 1) * 100
            })
        except: continue
        
    return pd.DataFrame(results)

if tickers:
    analysis_df = analyze_market(tickers)
    
    if not analysis_df.empty:
        # 섹터 매핑
        analysis_df['Sector'] = analysis_df['Ticker'].map(sector_dict)
        analysis_df['Sector'] = analysis_df['Sector'].fillna('기타')

        # 1. 주도 섹터
        sector_perf = analysis_df.groupby('Sector')['YTD'].mean().sort_values(ascending=False)
        top_sector = sector_perf.index[0]

        st.success(f"🏆 현재 S&P 500 주도 섹터: **{top_sector}**")
        st.metric("섹터 평균 YTD 수익률", f"{sector_perf[0]:.2f}%")

        # 2. 섹터 내 TOP 3
        st.subheader(f"🚀 {top_sector} 성과 상위 종목")
        top_3 = analysis_df[analysis_df['Sector'] == top_sector].sort_values('YTD', ascending=False).head(3)
        st.dataframe(top_3[['Ticker', 'YTD']].style.format({'YTD': '{:.2f}%'}))

        # 3. 눌림목 추천
        st.divider()
        st.subheader(f"🔍 {top_sector} 기술적 눌림목 추천")
        
        def get_signal(r):
            if not r['MA50_UP'] or r['Price'] < r['MA50'] * 0.95: return None
            for ma, label in zip([r['MA100'], r['MA50'], r['MA20']], ['100주선', '50주선', '20주선']):
                if abs(r['Price'] - ma) / ma < 0.03: return label
            return None

        leader_df = analysis_df[analysis_df['Sector'] == top_sector].copy()
        leader_df['Signal'] = leader_df.apply(get_signal, axis=1)
        recs = leader_df[leader_df['Signal'].notnull()].head(3)

        if not recs.empty:
            st.table(recs[['Ticker', 'YTD', '1Y_High_Drop', '2Y_High_Drop', '3Y_High_Drop', 'Signal']])
        else:
            st.info("조건에 맞는 눌림목 종목이 현재 섹터에 없습니다.")
    else:
        st.error("데이터 분석 결과가 없습니다. Yahoo Finance의 일시적 차단일 수 있으니 잠시 후 다시 시도해 주세요.")
