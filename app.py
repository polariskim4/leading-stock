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
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 S&P 500 섹터별 정확한 성과 및 눌림목 분석")

# --- 1. 날짜 설정 (에러 수정됨) ---
today = datetime.now()
last_year_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 리스트 가져오기 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(io.StringIO(res.text))
        df = tables[0]
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
    selected_sector = st.sidebar.selectbox("분석 섹터 선택", sectors)
    target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 종목: {len(target_tickers)}개")
    run_analysis = st.sidebar.button(f"{selected_sector} 분석 시작")

    if run_analysis:
        analysis_results = []
        # SMA 100 계산을 위해 3년치 데이터 확보
        hist_start = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status("실시간 데이터 분석 중...", expanded=True) as status:
            chunk_size = 10
            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                try:
                    # [에러 수정 포인트]: 시간 문자열 " 23:59:59"를 제거했습니다.
                    ytd_base_df = yf.download(chunk, start=last_year_start, end=last_year_end, 
                                             interval="1d", group_by='ticker', session=session, threads=False, progress=False)
                    
                    w_data = yf.download(chunk, start=hist_start, end=today_str, 
                                        interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data.columns.levels[0]: continue
                            
                            # YTD 기준점 종가 확보
                            if ticker in ytd_base_df.columns.levels[0]:
                                t_base = ytd_base_df[ticker].dropna()
                                if t_base.empty: continue
                                base_price = t_base['Close'].iloc[-1]
                            else: continue

                            df = w_data[ticker].dropna()
                            if len(df) < 100: continue 

                            close = df['Close']
                            curr_p = close.iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100

                            # 이동평균선 계산
                            ma20 = close.rolling(20).mean().iloc[-1]
                            ma50 = close.rolling(50).mean().iloc[-1]
                            ma100 = close.rolling(100).mean().iloc[-1]

                            # --- 배제 기준: SMA 50 > 100 정배열만 확인 ---
                            if not (ma50 > ma100):
                                continue

                            # 인접도 계산
                            dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                            dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                            
                            analysis_results.append({
                                'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                '1Y_고점대비': ((curr_p / close.tail(52).max()) - 1) * 100,
                                '2Y_고점대비': ((curr_p / close.tail(104).max()) - 1) * 100,
                                '3Y_고점대비': ((curr_p / close.tail(156).max()) - 1) * 100,
                                '인접도': min(dist_ma20, dist_ma50),
                                '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                            })
                        except: continue
                except Exception as e:
                    st.warning(f"청크 처리 중 오류 발생: {e}")
                
                time.sleep(random.uniform(0.5, 1.0))
            status.update(label="분석 완료!", state="complete")

        if analysis_results:
            final_df = pd.DataFrame(analysis_results)
            
            # --- 성과 상위 TOP 3 ---
            st.subheader(f"🏆 {selected_sector} 올해 성과 상위 TOP 3")
            top_3 = final_df.sort_values('YTD', ascending=False).head(3)
            st.dataframe(
                top_3[['Ticker', '현재가', 'YTD']].style.format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )

            # --- 눌림목 추천 TOP 5 ---
            st.divider()
            st.subheader("🔍 SMA 이동평균선 눌림목 추천 TOP 5")
            st.caption("조건: 주봉 SMA 50 > 100 정배열 유지 종목 중 이격도 최저순")
            
            recs = final_df.sort_values('인접도').head(5)
            st.dataframe(
                recs[['Ticker', '현재가', 'YTD', '1Y_고점대비', '2Y_고점대비', '3Y_고점대비', '인접SMA']].style
                .format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )
        else:
            st.warning("조건을 만족하는 종목을 찾지 못했습니다.")
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
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 S&P 500 섹터별 정확한 성과 및 눌림목 분석")

# --- 1. 날짜 설정 (에러 수정됨) ---
today = datetime.now()
last_year_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 리스트 가져오기 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(io.StringIO(res.text))
        df = tables[0]
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
    selected_sector = st.sidebar.selectbox("분석 섹터 선택", sectors)
    target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 종목: {len(target_tickers)}개")
    run_analysis = st.sidebar.button(f"{selected_sector} 분석 시작")

    if run_analysis:
        analysis_results = []
        # SMA 100 계산을 위해 3년치 데이터 확보
        hist_start = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status("실시간 데이터 분석 중...", expanded=True) as status:
            chunk_size = 10
            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                try:
                    # [에러 수정 포인트]: 시간 문자열 " 23:59:59"를 제거했습니다.
                    ytd_base_df = yf.download(chunk, start=last_year_start, end=last_year_end, 
                                             interval="1d", group_by='ticker', session=session, threads=False, progress=False)
                    
                    w_data = yf.download(chunk, start=hist_start, end=today_str, 
                                        interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data.columns.levels[0]: continue
                            
                            # YTD 기준점 종가 확보
                            if ticker in ytd_base_df.columns.levels[0]:
                                t_base = ytd_base_df[ticker].dropna()
                                if t_base.empty: continue
                                base_price = t_base['Close'].iloc[-1]
                            else: continue

                            df = w_data[ticker].dropna()
                            if len(df) < 100: continue 

                            close = df['Close']
                            curr_p = close.iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100

                            # 이동평균선 계산
                            ma20 = close.rolling(20).mean().iloc[-1]
                            ma50 = close.rolling(50).mean().iloc[-1]
                            ma100 = close.rolling(100).mean().iloc[-1]

                            # --- 배제 기준: SMA 50 > 100 정배열만 확인 ---
                            if not (ma50 > ma100):
                                continue

                            # 인접도 계산
                            dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                            dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                            
                            analysis_results.append({
                                'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                '1Y_고점대비': ((curr_p / close.tail(52).max()) - 1) * 100,
                                '2Y_고점대비': ((curr_p / close.tail(104).max()) - 1) * 100,
                                '3Y_고점대비': ((curr_p / close.tail(156).max()) - 1) * 100,
                                '인접도': min(dist_ma20, dist_ma50),
                                '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50'
                            })
                        except: continue
                except Exception as e:
                    st.warning(f"청크 처리 중 오류 발생: {e}")
                
                time.sleep(random.uniform(0.5, 1.0))
            status.update(label="분석 완료!", state="complete")

        if analysis_results:
            final_df = pd.DataFrame(analysis_results)
            
            # --- 성과 상위 TOP 3 ---
            st.subheader(f"🏆 {selected_sector} 올해 성과 상위 TOP 3")
            top_3 = final_df.sort_values('YTD', ascending=False).head(3)
            st.dataframe(
                top_3[['Ticker', '현재가', 'YTD']].style.format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )

            # --- 눌림목 추천 TOP 5 ---
            st.divider()
            st.subheader("🔍 SMA 이동평균선 눌림목 추천 TOP 5")
            st.caption("조건: 주봉 SMA 50 > 100 정배열 유지 종목 중 이격도 최저순")
            
            recs = final_df.sort_values('인접도').head(5)
            st.dataframe(
                recs[['Ticker', '현재가', 'YTD', '1Y_고점대비', '2Y_고점대비', '3Y_고점대비', '인접SMA']].style
                .format(precision=1).set_properties(**{'text-align': 'right'}),
                hide_index=True, width="stretch"
            )
        else:
            st.warning("조건을 만족하는 종목을 찾지 못했습니다.")
