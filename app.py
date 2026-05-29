import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Sector Analyst", layout="wide")

# --- 1. 날짜 및 초기 설정 ---
today = datetime.now()
last_year_end = datetime(today.year - 1, 12, 31).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

st.title("📊 S&P 500 섹터별 눌림목 분석기")
st.markdown("> **차단 방지 모드**: 선택한 섹터의 종목들만 안정적으로 분석합니다.")

# --- 2. S&P 500 종목 리스트 캐싱 ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        # 티커 세척
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
        # 연도와 같은 숫자 데이터 제거
        df = df[~df['Symbol'].str.isnumeric()]
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"종목 리스트를 불러오지 못했습니다: {e}")
        return pd.DataFrame()

sp500_data = get_sp500_list()

if not sp500_data.empty:
    # 사이드바에서 섹터 선택
    all_sectors = sorted(sp500_data['GICS Sector'].unique())
    selected_sector = st.sidebar.selectbox("분석할 섹터 선택", all_sectors)
    
    # 해당 섹터 티커만 추출
    target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_sector]['Symbol'].tolist()
    
    st.sidebar.write(f"선택 섹터 종목 수: {len(target_tickers)}개")
    run_analysis = st.sidebar.button(f"{selected_sector} 분석 시작")

    if run_analysis:
        # --- 3. 가격 데이터 분석 (선택된 섹터만) ---
        analysis_results = []
        start_history = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        
        # Yahoo Finance 세션 설정
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        progress_bar = st.progress(0)
        status_text = st.empty()

        with st.spinner(f"{selected_sector} 데이터를 가져오는 중..."):
            # 차단 방지를 위해 10개씩 끊어서 요청 (Chunking)
            chunk_size = 10
            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                status_text.text(f"진행 상황: {i}/{len(target_tickers)} 종목 완료")
                
                try:
                    # threads=False로 안정성 확보
                    data = yf.download(chunk, start=start_history, end=today_str, 
                                       interval="1wk", group_by='ticker', 
                                       session=session, threads=False, progress=False)
                    
                    for ticker in chunk:
                        if ticker not in data.columns.levels[0]: continue
                        df = data[ticker].dropna()
                        if len(df) < 52: continue

                        adj_close = df['Adj Close']
                        curr_p = adj_close.iloc[-1]
                        
                        # YTD 계산
                        ytd_start_data = adj_close.loc[last_year_end:]
                        if ytd_start_data.empty: continue
                        ytd_val = ((curr_p / ytd_start_data.iloc[0]) - 1) * 100

                        # 이동평균선
                        ma20 = adj_close.rolling(20).mean().iloc[-1]
                        ma50 = adj_close.rolling(50).mean().iloc[-1]
                        ma50_prev = adj_close.rolling(50).mean().iloc[-5]
                        ma100 = adj_close.rolling(100).mean().iloc[-1]

                        analysis_results.append({
                            'Ticker': ticker, 'YTD': ytd_val, '현재가': curr_p,
                            'MA20': ma20, 'MA50': ma50, 'MA100': ma100,
                            'MA50_UP': ma50 > ma50_prev,
                            '1Y_고점대비': ((curr_p / adj_close.tail(52).max()) - 1) * 100,
                            '2Y_고점대비': ((curr_p / adj_close.tail(104).max()) - 1) * 100,
                            '3Y_고점대비': ((curr_p / adj_close.tail(156).max()) - 1) * 100
                        })
                except Exception as e:
                    st.warning(f"{ticker} 분석 중 오류 발생: {e}")
                
                # 차단 방지를 위한 랜덤 지연
                time.sleep(random.uniform(1.0, 2.0))
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

            status_text.empty()
            progress_bar.empty()

        # --- 4. 결과 출력 ---
        if analysis_results:
            final_df = pd.DataFrame(analysis_results)
            
            # 섹터 내 TOP 3 종목
            st.subheader(f"🚀 {selected_sector} 수익률 상위 종목")
            top_3 = final_df.sort_values('YTD', ascending=False).head(3)
            st.table(top_3[['Ticker', 'YTD']].rename(columns={'YTD': 'YTD 수익률(%)'}))

            # 눌림목 추천
            st.divider()
            st.subheader(f"🔍 {selected_sector} 눌림목 추천 (Buy Signal)")
            
            def get_dip_signal(r):
                # 50주선 상승 추세 & 50주선 지지 확인
                if not r['MA50_UP'] or r['현재가'] < r['MA50'] * 0.95: return None
                # 100 > 50 > 20 순서로 근접도 체크
                for ma, label in zip([r['MA100'], r['MA50'], r['MA20']], ['100주선', '50주선', '20주선']):
                    if abs(r['현재가'] - ma) / ma < 0.03: return label
                return None

            final_df['Signal'] = final_df.apply(get_dip_signal, axis=1)
            recs = final_df[final_df['Signal'].notnull()].head(3)

            if not recs.empty:
                st.dataframe(recs[['Ticker', 'YTD', '1Y_고점대비', '2Y_고점대비', '3Y_고점대비', 'Signal']].style.format(precision=2))
            else:
                st.info(f"현재 {selected_sector} 섹터에 조건에 맞는 눌림목 종목이 없습니다.")
        else:
            st.error("데이터 분석에 실패했습니다. 섹터를 바꿔서 다시 시도해 보세요.")
else:
    st.warning("분석 대상을 불러오는 중입니다...")
