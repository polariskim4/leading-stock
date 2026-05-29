import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Trend Analyzer", layout="wide")

# UI 스타일 개선 (컴팩트 & 폰트 조절)
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    div[data-testid="stMetricValue"] { font-size: 1.3rem; }
    thead tr th { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 S&P 500 섹터별 눌림목 분석기")

# --- 1. 날짜 및 초기 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 리스트 가져오기 (종목명 & 섹터) ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        # 티커 세척 (BRK.B -> BRK-B)
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        # 숫자로 된 데이터 제외
        df = df[~df['Symbol'].str.isnumeric()]
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"S&P 500 데이터 로드 실패: {e}")
        return pd.DataFrame()

sp500_data = get_sp500_list()

if not sp500_data.empty:
    sectors = sorted(sp500_data['GICS Sector'].unique())
    selected_sector = st.sidebar.selectbox("섹터 선택", sectors)
    target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 종목: {len(target_tickers)}개")
    run_analysis = st.sidebar.button(f"{selected_sector} 분석 시작")

    if run_analysis:
        analysis_results = []
        # 주봉 기준 충분한 데이터 확보 (3년치)
        start_history = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        progress_bar = st.progress(0)
        
        chunk_size = 10
        for i in range(0, len(target_tickers), chunk_size):
            chunk = target_tickers[i:i + chunk_size]
            try:
                data = yf.download(chunk, start=start_history, end=today_str, 
                                   interval="1wk", group_by='ticker', 
                                   session=session, threads=False, progress=False)
                
                for ticker in chunk:
                    try:
                        if ticker not in data.columns.levels[0]: continue
                        df = data[ticker].dropna()
                        if len(df) < 100: continue # MA 100 계산을 위해 최소 100주 필요

                        close = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
                        curr_p = close.iloc[-1]
                        
                        # 이동평균선 계산 (주봉)
                        ma20 = close.rolling(20).mean().iloc[-1]
                        ma50 = close.rolling(50).mean().iloc[-1]
                        ma100 = close.rolling(100).mean().iloc[-1]
                        
                        # --- 배제 기준 수정: SMA 50이 정배열이 아닌 경우(MA 50 < MA 100)만 배제 ---
                        if not (ma50 > ma100):
                            continue
                        
                        # 이평선 근접도 (20주선 혹은 50주선과의 거리)
                        dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                        dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                        min_dist = min(dist_ma20, dist_ma50)
                        
                        # YTD 수익률
                        ytd_start_val = close.loc[last_year_end:].iloc[0]
                        ytd_val = ((curr_p / ytd_start_val) - 1) * 100

                        analysis_results.append({
                            'Ticker': ticker,
                            '현재가': curr_p,
                            'YTD(%)': ytd_val,
                            '1Y_고점대비': ((curr_p / close.tail(52).max()) - 1) * 100,
                            '2Y_고점대비': ((curr_p / close.tail(104).max()) - 1) * 100,
                            '3Y_고점대비': ((curr_p / close.tail(156).max()) - 1) * 100,
                            '근접도': min_dist,
                            '대상MA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                        })
                    except: continue
            except: pass
            
            time.sleep(random.uniform(0.3, 0.7))
            progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

        if analysis_results:
            final_df = pd.DataFrame(analysis_results)
            # 이평선 근처에 붙어있는 순서로 정렬
            final_df = final_df.sort_values('근접도').head(3)

            st.subheader(f"🚀 {selected_sector} 눌림목 추천 (SMA 50 우상향 종목)")
            
            # 컬럼 이름 및 소수점/정렬 설정
            display_df = final_df.drop(columns=['근접도']).rename(columns={
                '1Y_고점대비': '1년고점대비(%)',
                '2Y_고점대비': '2년고점대비(%)',
                '3Y_고점대비': '3년고점대비(%)',
                '대상MA': '인접 이평선'
            })

            # 테이블 출력
            st.dataframe(
                display_df.style.format(precision=1, subset=['현재가', 'YTD(%)', '1년고점대비(%)', '2년고점대비(%)', '3년고점대비(%)'])
                .set_properties(**{'text-align': 'right'}),
                hide_index=True,
                use_container_width=True
            )
        else:
            st.info("조건을 만족하는 눌림목 종목이 현재 섹터에 없습니다.")

# --- 추가 조언 ---
with st.expander("📌 전문가의 눌림목 판별 팁"):
    st.write("""
    1. **SMA 50 > 100 (추세 확인)**: 50주선이 100주선 위에 있다는 것은 거대한 상승 사이클이 깨지지 않았음을 의미합니다.
    2. **거래량 확인**: 주가가 이평선에 닿을 때 거래량이 줄어들면 '매도세의 소멸'로 보며, 이후 거래량이 실린 양봉이 나오면 최적의 타이밍입니다.
    3. **RSI 과매도**: 주봉 RSI가 40-50 사이에서 지지를 받는다면 강력한 지지선이 형성된 것으로 봅니다.
    """)
