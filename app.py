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

# UI 스타일 개선 (컴팩트 & 우측 정렬)
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 S&P 500 주도주 및 SMA 눌림목 분석")
st.info("Yahoo Finance 차단 방지를 위해 데이터를 소량씩 천천히 분석합니다. 잠시만 기다려주세요.")

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 종목 리스트 가져오기 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        # 티커 세척
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        df = df[~df['Symbol'].str.isnumeric()]
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"리스트 로드 실패: {e}")
        return pd.DataFrame()

sp500_data = get_sp500_list()

if not sp500_data.empty:
    sectors = sorted(sp500_data['GICS Sector'].unique())
    selected_sector = st.sidebar.selectbox("분석할 섹터 선택", sectors)
    target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"분석 대상 종목: {len(target_tickers)}개")
    run_analysis = st.sidebar.button(f"{selected_sector} 분석 시작")

    if run_analysis:
        analysis_results = []
        # 주봉 기준 MA 100을 위해 3년치 데이터 수집
        start_history = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        
        # Yahoo Finance 세션 설정
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        progress_bar = st.progress(0)
        status_text = st.empty()

        # 차단 방지를 위해 아주 작은 청크(5개)로 나눔
        chunk_size = 5
        for i in range(0, len(target_tickers), chunk_size):
            chunk = target_tickers[i:i + chunk_size]
            status_text.text(f"데이터 수집 중: {i}/{len(target_tickers)} 완료...")
            
            try:
                # threads=False 필수 (차단 회피)
                data = yf.download(chunk, start=start_history, end=today_str, 
                                   interval="1wk", group_by='ticker', 
                                   session=session, threads=False, progress=False)
                
                for ticker in chunk:
                    try:
                        if ticker not in data.columns.levels[0]: continue
                        df = data[ticker].dropna()
                        if len(df) < 100: continue

                        # Adj Close가 없으면 Close 사용
                        close = df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
                        curr_p = close.iloc[-1]
                        
                        # 이동평균선 (주봉)
                        ma20 = close.rolling(20).mean().iloc[-1]
                        ma50 = close.rolling(50).mean().iloc[-1]
                        ma100 = close.rolling(100).mean().iloc[-1]
                        
                        # [조건 1] 장기 우상향: SMA 50 > SMA 100
                        if not (ma50 > ma100): continue
                        
                        # YTD 수익률
                        ytd_start_data = close.loc[last_year_end:]
                        if ytd_start_data.empty: continue
                        ytd_val = ((curr_p / ytd_start_data.iloc[0]) - 1) * 100

                        # [조건 2] SMA 인접도 계산 (20 혹은 50과의 거리)
                        dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                        dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                        min_dist = min(dist_ma20, dist_ma50)

                        analysis_results.append({
                            'Ticker': ticker,
                            'YTD': ytd_val,
                            '현재가': curr_p,
                            '1Y_고점대비': ((curr_p / close.tail(52).max()) - 1) * 100,
                            '2Y_고점대비': ((curr_p / close.tail(104).max()) - 1) * 100,
                            '3Y_고점대비': ((curr_p / close.tail(156).max()) - 1) * 100,
                            '인접도': min_dist,
                            '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                        })
                    except: continue
            except: 
                st.warning(f"일부 종목({chunk}) 호출 중 차단이 의심됩니다. 잠시 후 재개합니다.")
                time.sleep(5)
            
            # 요청 간 랜덤 지연 (차단 회피 핵심)
            time.sleep(random.uniform(1.5, 3.0))
            progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

        status_text.empty()
        progress_bar.empty()

        if analysis_results:
            final_df = pd.DataFrame(analysis_results)
            
            # --- 성과 상위 종목 TOP 3 ---
            st.subheader(f"🏆 {selected_sector} 성과 상위 TOP 3 (YTD)")
            top_3 = final_df.sort_values('YTD', ascending=False).head(3)
            st.dataframe(
                top_3[['Ticker', '현재가', 'YTD']].style.format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )

            # --- 눌림목 추천 종목 TOP 5 ---
            st.divider()
            st.subheader("🔍 SMA 이동평균선 눌림목 추천 TOP 5")
            st.caption("장기 정배열(SMA 50 > 100) 종목 중 SMA 20 또는 50에 가장 인접한 종목")
            
            recs = final_df.sort_values('인접도').head(5)
            display_recs = recs.rename(columns={
                'YTD': 'YTD(%)',
                '현재가': '현재가($)',
                '1Y_고점대비': '1년고점대비(%)',
                '2Y_고점대비': '2년고점대비(%)',
                '3Y_고점대비': '3년고점대비(%)',
                '인접SMA': '인접 이평선'
            })

            st.dataframe(
                display_recs[['Ticker', '현재가($)', 'YTD(%)', '1년고점대비(%)', '2년고점대비(%)', '3년고점대비(%)', '인접 이평선']].style
                .format(precision=1)
                .set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )
        else:
            st.error("분석 결과가 없습니다. Yahoo Finance의 차단이 너무 강력합니다. 잠시 후 다시 시도하시거나 다른 섹터를 선택해 보세요.")
