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

# UI 스타일 개선 (컴팩트 & 우측 정렬)
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 S&P 500 주도주 및 SMA 눌림목 추천")

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
    selected_sector = st.sidebar.selectbox("섹터 선택", sectors)
    tickers = sp500_df[sp500_df['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상: {len(tickers)}개 종목")
    run = st.sidebar.button(f"{selected_sector} 분석 시작")

    if run:
        results = []
        # 주봉 기준 데이터 수집 (3년치)
        start_date = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()
        
        progress_bar = st.progress(0)
        chunk_size = 15 # 속도 향상을 위해 청크 사이즈 조절
        
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            try:
                data = yf.download(chunk, start=start_date, end=today_str, interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                
                for ticker in chunk:
                    try:
                        if ticker not in data.columns.levels[0]: continue
                        df = data[ticker].dropna()
                        if len(df) < 100: continue

                        close = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
                        curr_p = close.iloc[-1]
                        
                        # 이동평균선 계산 (주봉)
                        ma20 = close.rolling(20).mean().iloc[-1]
                        ma50 = close.rolling(50).mean().iloc[-1]
                        ma100 = close.rolling(100).mean().iloc[-1]
                        
                        # 1. 정배열 필터 (SMA 50 > SMA 100) - 우상향 추세 확인
                        if not (ma50 > ma100): continue
                        
                        # 2. 수익률 및 이격도 계산
                        ytd_start_price = close.loc[last_year_end:].iloc[0]
                        ytd_val = ((curr_p / ytd_start_price) - 1) * 100
                        dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                        dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                        
                        results.append({
                            'Ticker': ticker,
                            'YTD': ytd_val,
                            '현재가': curr_p,
                            '1년고점대비': ((curr_p / close.tail(52).max()) - 1) * 100,
                            '2년고점대비': ((curr_p / close.tail(104).max()) - 1) * 100,
                            '3년고점대비': ((curr_p / close.tail(156).max()) - 1) * 100,
                            '인접도': min(dist_ma20, dist_ma50),
                            '대상MA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                        })
                    except: continue
            except: pass
            time.sleep(random.uniform(0.3, 0.6))
            progress_bar.progress(min((i + chunk_size) / len(tickers), 1.0))

        if results:
            full_res = pd.DataFrame(results)
            
            # --- 1. 성과 상위 종목 TOP 3 (YTD 기준) ---
            st.subheader(f"🏆 {selected_sector} 올해 성과 상위 TOP 3")
            top_3 = full_res.sort_values('YTD', ascending=False).head(3)
            st.dataframe(
                top_3[['Ticker', '현재가', 'YTD']].style.format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, use_container_width=True
            )

            # --- 2. 눌림목 추천 종목 TOP 5 (인접도 기준) ---
            st.divider()
            st.subheader(f"🔍 SMA 이동평균선 눌림목 추천 TOP 5")
            st.caption("장기 정배열(SMA 50 > 100) 종목 중 현재 주가가 SMA 20 또는 50에 가장 근접한 종목")
            
            # 인접도(이격도)가 가장 낮은 순서로 정렬
            recommendations = full_res.sort_values('인접도').head(5)
            
            # 출력용 데이터프레임 정리
            display_rec = recommendations.rename(columns={
                'YTD': 'YTD(%)', '현재가': '현재가($)', '1년고점대비': '1년고점대비(%)',
                '2년고점대비': '2년고점대비(%)', '3년고점대비': '3년고점대비(%)',
                '대상MA': '인접 이평선'
            })

            st.dataframe(
                display_rec[['Ticker', '현재가($)', 'YTD(%)', '1년고점대비(%)', '2년고점대비(%)', '3년고점대비(%)', '인접 이평선']].style
                .format(precision=1)
                .set_properties(**{'text-align': 'right'}),
                hide_index=True, use_container_width=True
            )
        else:
            st.warning("조건에 부합하는 종목을 찾지 못했습니다. 장기 추세가 우상향(SMA 50 > 100)인 종목이 해당 섹터에 없을 수 있습니다.")

# 설명 섹션
with st.expander("ℹ️ 분석 로직 가이드"):
    st.write("""
    - **정배열 조건**: 주봉 기준 SMA 50이 SMA 100보다 위에 있는 종목만 선별하여 장기 상승 추세임을 보장합니다.
    - **눌림목 정렬**: 현재 주가가 SMA 20 또는 SMA 50 이동평균선에 가장 가깝게 붙어 있는(이격도가 낮은) 종목을 상위에 노출합니다.
    - **UI 설정**: 모든 수치는 소수점 첫째 자리까지 표시하며, 인덱스 없이 깔끔하게 우측 정렬됩니다.
    """)
