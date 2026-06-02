import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="Market Alpha Hunter", layout="wide")

# UI 스타일 개선
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 거래량 기반 눌림목 추천")

# --- 1. 날짜 설정 (오류 수정) ---
today = datetime.now()
# YTD 계산을 위해 작년 12월 20일부터 올해 1월 1일까지 범위를 잡아 데이터를 가져옵니다.
last_year_start_range = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end_range = datetime(today.year, 1, 2).strftime('%Y-%m-%d') 
today_str = today.strftime('%Y-%m-%d')

# --- 2. 데이터 소스 가져오기 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        df = df[~df['Symbol'].str.isnumeric()]
        return df[['Symbol', 'GICS Sector']]
    except: return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_nasdaq100_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Ticker')[0]
        ticker_col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
        tickers = df[ticker_col].astype(str).str.replace('.', '-', regex=False).str.strip().tolist()
        return [t for t in tickers if t and not t.isdigit() and t != 'nan']
    except: return []

@st.cache_data(ttl=86400)
def get_dow30_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        ticker_col = 'Symbol' if 'Symbol' in df.columns else df.columns[1]
        tickers = df[ticker_col].astype(str).str.replace('.', '-', regex=False).str.strip().tolist()
        return [t for t in tickers if t and not t.isdigit() and t != 'nan']
    except: return []

sp500_data = get_sp500_list()

if not sp500_data.empty:
    gics_sectors = sorted(sp500_data['GICS Sector'].unique().tolist())
    menu_options = gics_sectors + ["Nasdaq100", "Dow30"]
    selected_menu = st.sidebar.selectbox("분석 대상 선택", menu_options, key="market_selector")
    
    if selected_menu == "Nasdaq100":
        target_tickers = get_nasdaq100_list()
    elif selected_menu == "Dow30":
        target_tickers = get_dow30_list()
    else:
        target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_menu]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상: {len(target_tickers)}개 종목")
    run_analysis = st.sidebar.button(f"{selected_menu} 분석 시작")

    if run_analysis:
        performance_results = []
        recommendation_results = []
        
        hist_start = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status(f"{selected_menu} 데이터 분석 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            status_text = st.empty()
            chunk_size = 15

            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                status_text.text(f"처리 중: {i}/{len(target_tickers)} 종목 완료")
                try:
                    # YTD 기준가를 잡기 위해 작년 말 데이터를 범위로 가져옴 (오류 방지를 위해 start/end 다르게 설정)
                    ytd_base_df = yf.download(chunk, start=last_year_start_range, 
                                             end=last_year_end_range, interval="1d", group_by='ticker', session=session, threads=False, progress=False)
                    w_data = yf.download(chunk, start=hist_start, end=today_str, 
                                        interval="1wk", group_by='ticker', session=session, threads=False, progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data.columns.levels[0] or ticker not in ytd_base_df.columns.levels[0]: continue
                            
                            t_base = ytd_base_df[ticker].dropna()
                            w_df = w_data[ticker].dropna()
                            if t_base.empty or len(w_df) < 100: continue

                            # 작년 말 마지막 거래일의 종가
                            base_price = t_base['Close'].iloc[-1]
                            curr_p = w_df['Close'].iloc[-1]
                            curr_v = w_df['Volume'].iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100

                            # 1. 성과 데이터 저장
                            performance_results.append({
                                'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret
                            })

                            # 2. 기술적 지표 계산
                            ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                            ma50 = w_df['Close'].rolling(50).mean().iloc[-1]
                            ma100 = w_df['Close'].rolling(100).mean().iloc[-1]
                            max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                            vol_ratio = (curr_v / max_v_8w) if max_v_8w > 0 else 1.0

                            # 눌림목 필터 적용
                            if (ma50 > ma100) and (vol_ratio <= 0.65):
                                dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                                dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                                min_dist = min(dist_ma20, dist_ma50)

                                # --- 종합 점수 계산 (인접도 가중치 + 거래량 감소 가중치) ---
                                score = ( (1 - min_dist/10) * 60 ) + ( (1 - vol_ratio) * 40 )
                                
                                recommendation_results.append({
                                    'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                    '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                    '거래량비중(%)': vol_ratio * 100,
                                    '인접도': min_dist,
                                    '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50',
                                    '종합점수': max(0, round(score, 1))
                                })
                        except: continue
                except: pass
                time.sleep(random.uniform(0.5, 0.8))
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))
            
            status_text.empty()
            progress_bar.empty()
            status.update(label="분석 완료!", state="complete")

        # --- 결과 출력 ---
        if performance_results:
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(performance_results)
            top_3 = perf_df.sort_values('YTD', ascending=False).head(3)
            st.dataframe(top_3.style.format(precision=1), hide_index=True, width="stretch")

            st.divider()
            st.subheader(f"🔍 {selected_menu} 기술적 눌림목 추천 TOP 10")
            if recommendation_results:
                recs_df = pd.DataFrame(recommendation_results)
                # 종합점수 기준 내림차순 정렬 후 상위 10개 표시
                recs = recs_df.sort_values('종합점수', ascending=False).head(10)
                # 종합점수를 가장 마지막 컬럼으로 배치
                display_cols = ['Ticker', '현재가', 'YTD', '1Y_고점대비', '거래량비중(%)', '인접SMA', '종합점수']
                st.dataframe(recs[display_cols].style.format(precision=1), 
                             hide_index=True, width="stretch")
            else:
                st.info("현재 눌림목 조건을 만족하는 종목이 없습니다.")
        else:
            st.error("데이터를 불러오는 데 실패했습니다. 날짜 설정이나 네트워크 상태를 확인해주세요.")
