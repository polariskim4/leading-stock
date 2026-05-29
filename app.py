import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Alpha Hunter", layout="wide")

# UI 스타일 개선
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem; }
    thead tr th { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 S&P 500 섹터 주도주 및 눌림목 추천")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 유니버스 수집 ---
@st.cache_data(ttl=86400)
def get_sp500_universe():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        df = df[~df['Symbol'].str.isnumeric()]
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

sp500_df = get_sp500_universe()

if not sp500_df.empty:
    sectors = sorted(sp500_df['GICS Sector'].unique())
    selected_sector = st.sidebar.selectbox("관심 섹터 선택", sectors)
    tickers = sp500_df[sp500_df['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.info(f"분석 대상: {len(tickers)}개 종목")
    run = st.sidebar.button(f"{selected_sector} 정밀 분석 시작")

    if run:
        results = []
        start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()
        
        progress_bar = st.progress(0)
        chunk_size = 10
        
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            try:
                data = yf.download(chunk, start=start_date, end=today_str, interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                
                for ticker in chunk:
                    try:
                        if ticker not in data.columns.levels[0]: continue
                        df = data[ticker].dropna()
                        if len(df) < 104: continue # 2년치 데이터 확보

                        close = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
                        curr_p = close.iloc[-1]
                        
                        # 1. 이동평균선 및 정배열 확인
                        ma20 = close.rolling(20).mean().iloc[-1]
                        ma50 = close.rolling(50).mean().iloc[-1]
                        ma100 = close.rolling(100).mean().iloc[-1]
                        
                        # SMA 50 > 100 장기 정배열 필터
                        if not (ma50 > ma100): continue
                        
                        # 2. 피보나치 되돌림 계산 (최근 1년 기준)
                        high_1y = close.tail(52).max()
                        low_1y = close.tail(52).min()
                        diff = high_1y - low_1y
                        # 0.382(상단), 0.618(하단)
                        fib_high = low_1y + (diff * 0.618)
                        fib_low = low_1y + (diff * 0.382)
                        
                        # 3. 수익률 및 이격도
                        ytd_start = close.loc[last_year_end:].iloc[0]
                        ytd_val = ((curr_p / ytd_start) - 1) * 100
                        dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                        dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                        
                        results.append({
                            'Ticker': ticker,
                            'YTD': ytd_val,
                            'Price': curr_p,
                            '1Y_Drop': ((curr_p / high_1y) - 1) * 100,
                            '2Y_Drop': ((curr_p / close.tail(104).max()) - 1) * 100,
                            '3Y_Drop': ((curr_p / close.tail(156).max()) - 1) * 100,
                            'Min_Dist': min(dist_ma20, dist_ma50),
                            'Fib_Zone': "Yes" if fib_low <= curr_p <= fib_high else "No",
                            'Nearest_MA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                        })
                    except: continue
            except: pass
            time.sleep(random.uniform(0.3, 0.6))
            progress_bar.progress(min((i + chunk_size) / len(tickers), 1.0))

        if results:
            full_res = pd.DataFrame(results)
            
            # --- 성과 상위 종목 TOP 3 (YTD 기준) ---
            st.subheader(f"🏆 {selected_sector} 성과 상위 TOP 3 (YTD)")
            top_3 = full_res.sort_values('YTD', ascending=False).head(3)
            st.dataframe(
                top_3[['Ticker', 'Price', 'YTD']].style.format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, use_container_width=True
            )

            # --- 추천 종목 TOP 5 (SMA 인접도 우선) ---
            st.divider()
            st.subheader(f"🔍 기술적 눌림목 추천 TOP 5")
            st.caption("조건: SMA 50 > 100 정배열 유지 종목 중 이평선 인접도순 정렬")
            
            # 피보나치 존에 있는 종목을 가산점으로 둘 수도 있으나, 요청대로 SMA 인접도를 최우선 정렬
            recommendations = full_res.sort_values('Min_Dist').head(5)
            
            display_rec = recommendations.rename(columns={
                'YTD': 'YTD(%)', 'Price': '현재가($)', '1Y_Drop': '1년고점대비(%)',
                '2Y_Drop': '2년고점대비(%)', '3Y_Drop': '3년고점대비(%)',
                'Fib_Zone': '피보나치구간(0.382~0.618)', 'Nearest_MA': '인접 이평선'
            })

            st.dataframe(
                display_rec[['Ticker', '현재가($)', 'YTD(%)', '1년고점대비(%)', '2년고점대비(%)', '3년고점대비(%)', '피보나치구간(0.382~0.618)', '인접 이평선']].style
                .format(precision=1, subset=['현재가($)', 'YTD(%)', '1년고점대비(%)', '2년고점대비(%)', '3년고점대비(%)'])
                .set_properties(**{'text-align': 'right'}),
                hide_index=True, use_container_width=True
            )
        else:
            st.warning("조건에 부합하는 종목을 찾지 못했습니다. 잠시 후 다시 시도해 주세요.")

# 안내 문구
with st.expander("📚 분석 기준 안내"):
    st.write("""
    - **YTD**: 올해 첫 거래일 종가 대비 현재가 수익률
    - **정배열**: 주봉 기준 SMA 50이 SMA 100보다 위에 있어 장기 추세가 우상향인 상태
    - **피보나치 구간**: 최근 1년 고점과 저점 사이의 되돌림 0.382 ~ 0.618 수준 (건강한 조정 구간)
    - **인접 이평선**: 현재가와 SMA 20 또는 SMA 50 사이의 이격이 가장 적은 상태
    """)
