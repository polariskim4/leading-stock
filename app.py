import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Sector Dip-Buyer", layout="wide")

st.title("📈 S&P 500 섹터별 눌림목 분석기")
st.markdown("""
Yahoo Finance의 IP 차단을 피하기 위해 **섹터별 분할 분석** 모드로 작동합니다. 
분석을 원하는 섹터를 선택한 후 버튼을 눌러주세요.
""")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 리스트 가져오기 (종목명과 섹터만) ---
@st.cache_data(ttl=86400) # 리스트는 하루에 한 번만 가져옴
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        
        # 티커 정제 (연도 등 숫자 데이터 제거)
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        df = df[~df['Symbol'].str.isnumeric()]
        
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"S&P 500 리스트 로드 실패: {e}")
        return pd.DataFrame()

sp500_df = get_sp500_list()

if not sp500_df.empty:
    # 섹터 선택 사이드바
    sectors = sorted(sp500_df['GICS Sector'].unique())
    selected_sector = st.sidebar.selectbox("분석할 섹터를 선택하세요", sectors)
    
    # 해당 섹터 종목 필터링
    sector_tickers = sp500_df[sp500_df['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"선택된 섹터 종목 수: {len(sector_tickers)}개")
    start_button = st.sidebar.button(f"{selected_sector} 분석 시작")

    if start_button:
        # --- 3. 가격 데이터 분석 (선택된 섹터만) ---
        with st.status(f"{selected_sector} 종목 데이터 분석 중...", expanded=True) as status:
            start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
            
            session = requests.Session()
            session.headers.update({'User-Agent': 'Mozilla/5.0'})

            try:
                # 병렬 처리를 끄고(threads=False) 한 세션으로 요청
                data = yf.download(sector_tickers, start=start_date, end=today_str, 
                                   interval="1wk", group_by='ticker', 
                                   session=session, threads=False)
                
                results = []
                for ticker in sector_tickers:
                    try:
                        if ticker not in data.columns.levels[0]: continue
                        df = data[ticker].dropna()
                        if len(df) < 50: continue

                        close = df['Adj Close']
                        curr = close.iloc[-1]
                        
                        # YTD 계산 (데이터가 없을 경우 대비)
                        ytd_data = close.loc[last_year_end:]
                        if ytd_data.empty: continue
                        ytd_ret = ((curr / ytd_data.iloc[0]) - 1) * 100

                        # 지표 계산
                        ma20 = close.rolling(20).mean().iloc[-1]
                        ma50 = close.rolling(50).mean().iloc[-1]
                        ma50_prev = close.rolling(50).mean().iloc[-5]
                        ma100 = close.rolling(100).mean().iloc[-1]

                        results.append({
                            'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr,
                            'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                            'MA50_UP': ma50 > ma50_prev,
                            '1Y_High_Drop': ((curr / close.tail(52).max()) - 1) * 100,
                            '2Y_High_Drop': ((curr / close.tail(104).max()) - 1) * 100,
                            '3Y_High_Drop': ((curr / close.tail(156).max()) - 1) * 100
                        })
                    except: continue
                
                analysis_df = pd.DataFrame(results)
                
                if not analysis_df.empty:
                    # 1. 섹터 내 TOP 3 종목
                    st.subheader(f"🚀 {selected_sector} 내 수익률 TOP 3")
                    top_3 = analysis_df.sort_values('YTD', ascending=False).head(3)
                    st.table(top_3[['Ticker', 'YTD']].rename(columns={'YTD': 'YTD 수익률(%)'}))

                    # 2. 눌림목 추천
                    st.divider()
                    st.subheader(f"🔍 {selected_sector} 기술적 눌림목 추천")
                    
                    def get_signal(r):
                        # 50주선 상승 + 현재가가 50주선보다 위 (크게 안깨짐)
                        if not r['MA50_UP'] or r['현재가'] < r['MA50'] * 0.96: return None
                        # 100 > 50 > 20 순서로 근접도(3%) 확인
                        for ma, label in zip([r['MA100'], r['MA50'], r['MA20']], ['100주선', '50주선', '20주선']):
                            if abs(r['현재가'] - ma) / ma < 0.03: return label
                        return None

                    analysis_df['Signal'] = analysis_df.apply(get_signal, axis=1)
                    recs = analysis_df[analysis_df['Signal'].notnull()].head(3)

                    if not recs.empty:
                        st.dataframe(recs[['Ticker', 'YTD', '1Y_High_Drop', '2Y_High_Drop', '3Y_High_Drop', 'Signal']].style.format(precision=2))
                    else:
                        st.info(f"현재 {selected_sector} 섹터에 기술적 조건에 맞는 종목이 없습니다.")
                    
                    status.update(label="분석 완료!", state="complete")
                else:
                    st.error("데이터 수집에 실패했습니다. 잠시 후 다시 시도해 주세요.")
            except Exception as e:
                st.error(f"Yahoo Finance 접근 오류: {e}")

else:
    st.warning("분석할 종목 리스트를 불러오지 못했습니다.")
