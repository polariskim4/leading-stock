import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
from datetime import datetime, timedelta

# 페이지 설정
st.set_page_config(page_title="S&P 500 Real-time Leader", layout="wide")

st.title("🚀 S&P 500 실제 주도주 및 눌림목 분석")
st.markdown("""
현재 S&P 500 지수에 포함된 **실제 종목**만을 대상으로 분석합니다. 
(참고: SNDK는 2016년 상장폐지되어 리스트에서 제외되었습니다.)
""")

# --- 1. 날짜 설정 (정확한 YTD) ---
today = datetime.now()
# 작년 마지막 거래일 데이터를 가져오기 위해 12월 25일부터 조회
last_year_end = datetime(today.year - 1, 12, 25).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')

# --- 2. S&P 500 리스트 가져오기 (현재 구성 종목만 엄격히 필터링) ---
@st.cache_data(ttl=86400)
def get_sp500_current():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        # 첫 번째 테이블: "현재 구성 종목"
        tables = pd.read_html(io.StringIO(res.text))
        df = tables[0]
        
        # 컬럼명 유연하게 처리
        sym_col = 'Symbol' if 'Symbol' in df.columns else df.columns[0]
        sec_col = 'GICS Sector' if 'GICS Sector' in df.columns else 'Sector'
        
        df = df[[sym_col, sec_col]].rename(columns={sym_col: 'Ticker', sec_col: 'Sector'})
        df['Ticker'] = df['Ticker'].str.replace('.', '-', regex=False).str.strip()
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

sp500_df = get_sp500_current()

if not sp500_df.empty:
    sectors = sorted(sp500_df['Sector'].unique())
    selected_sector = st.sidebar.selectbox("섹터 선택", sectors)
    tickers = sp500_df[sp500_df['Sector'] == selected_sector]['Ticker'].tolist()
    
    if st.sidebar.button(f"{selected_sector} 분석 실행"):
        results = []
        # 정확한 비교를 위해 일봉(YTD용)과 주봉(추세용) 분리
        with st.status("실시간 데이터 분석 중...", expanded=True) as status:
            # yfinance 벌크 다운로드
            data = yf.download(tickers, start=last_year_end, end=today_str, interval="1d", group_by='ticker', threads=False)
            
            for ticker in tickers:
                try:
                    if ticker not in data.columns.levels[0]: continue
                    df = data[ticker].dropna()
                    if len(df) < 10: continue

                    # YTD 계산: 2024년 첫 거래일 종가 대비 현재가
                    first_price_2024 = df.loc[f"{today.year}-01-01":].iloc[0]['Close']
                    current_price = df['Close'].iloc[-1]
                    ytd_ret = ((current_price / first_price_2024) - 1) * 100

                    # 주봉 기준 이동평균선 (정확도를 위해 데이터 재생성)
                    # 주봉 이동평균선은 데이터가 많이 필요하므로 별도 계산 로직 권장
                    # 여기서는 간단한 일봉 기준 20/50선으로 대체하여 속도 확보
                    ma20 = df['Close'].rolling(20).mean().iloc[-1]
                    ma50 = df['Close'].rolling(50).mean().iloc[-1]
                    ma100 = df['Close'].rolling(100).mean().iloc[-1]

                    # SMA 50 > 100 정배열 확인
                    if ma50 > ma100:
                        dist_ma = min(abs(current_price - ma20)/ma20, abs(current_price - ma50)/ma50)
                        
                        results.append({
                            'Ticker': ticker,
                            'YTD': ytd_ret,
                            'Price': current_price,
                            'Dist_MA': dist_ma * 100,
                            '1Y_High_Drop': ((current_price / df['Close'].tail(252).max()) - 1) * 100
                        })
                except: continue
            status.update(label="분석 완료!", state="complete")

        if results:
            res_df = pd.DataFrame(results)
            
            # 성과 상위 TOP 3
            st.subheader(f"🏆 {selected_sector} 올해 성과 상위 (YTD)")
            st.dataframe(res_df.sort_values('YTD', ascending=False).head(3)[['Ticker', 'Price', 'YTD']].style.format(precision=1), hide_index=True, width="stretch")

            # 눌림목 추천 TOP 5
            st.divider()
            st.subheader("🔍 SMA 이동평균선 눌림목 추천")
            recs = res_df.sort_values('Dist_MA').head(5)
            st.dataframe(recs[['Ticker', 'Price', 'YTD', '1Y_High_Drop']].style.format(precision=1), hide_index=True, width="stretch")
