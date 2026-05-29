import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import requests
import io  # 문자열을 파일처럼 다루기 위해 필요합니다.

@st.cache_data(ttl=3600)
def get_stock_universe():
    try:
        # 위키피디아의 봇 차단을 방지하기 위한 브라우저 헤더 설정
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # 1. S&P 500 종목 및 섹터 정보 가져오기
        sp500_url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        res_sp500 = requests.get(sp500_url, headers=headers)
        # io.StringIO를 사용하여 HTML 텍스트를 감싸줍니다.
        sp500_df = pd.read_html(io.StringIO(res_sp500.text))[0]
        sp500_df = sp500_df[['Symbol', 'GICS Sector']].rename(columns={'Symbol': 'Ticker', 'GICS Sector': 'Sector'})
        
        # 2. Nasdaq 100 티커 가져오기
        nas_url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        res_nas = requests.get(nas_url, headers=headers)
        ndx_tickers = pd.read_html(io.StringIO(res_nas.text))[4]['Ticker'].tolist()
        
        # 3. Dow Jones 30 티커 가져오기
        dow_url = 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average'
        res_dow = requests.get(dow_url, headers=headers)
        dow_tickers = pd.read_html(io.StringIO(res_dow.text))[1]['Symbol'].tolist()
        
        # 중복 제거 및 티커 포맷 정리 (예: BRK.B -> BRK-B)
        all_tickers = list(set(sp500_df['Ticker'].tolist() + ndx_tickers + dow_tickers))
        all_tickers = [t.replace('.', '-') for t in all_tickers]
        
        return sp500_df, all_tickers
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(), []
