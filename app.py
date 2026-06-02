import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
from pandas_datareader import data as pdr

# 1. 페이지 설정
st.set_page_config(page_title="Stock Sector & Pullback Analyzer", layout="wide")

@st.cache_data(ttl=3600)
def get_stock_data(tickers):
    # 효율적인 데이터 로드를 위해 한 번에 다운로드
    data = yf.download(tickers, period="4y", interval="1d", progress=False)
    return data['Close']

def get_sector_mapping():
    # S&P500, Nasdaq100, Dow30의 주요 기업과 섹터 매핑 (간소화 버전)
    # 실제 운영시에는 info를 사용하거나 미리 정의된 CSV를 사용하는 것이 속도면에서 유리함
    return {
        "AAPL": "Information Technology", "MSFT": "Information Technology", "NVDA": "Information Technology",
        "GOOGL": "Communication Services", "META": "Communication Services", "NFLX": "Communication Services",
        "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary", "ORCL": "Information Technology",
        "JPM": "Financials", "GS": "Financials", "V": "Financials",
        "JNJ": "Health Care", "UNH": "Health Care", "PFE": "Health Care",
        "XOM": "Energy", "CVX": "Energy", "PG": "Consumer Staples",
        "COST": "Consumer Staples", "AMT": "Real Estate", "NEE": "Utilities"
    }

def calculate_drawdown(price_series, years):
    days = int(252 * years)
    recent_prices = price_series.iloc[-days:]
    peak = recent_prices.max()
    current = price_series.iloc[-1]
    return ((current - peak) / peak) * 100

# 메인 앱 로직
def main():
    st.title("🚀 주도 섹터 및 주도주 눌림목 분석기")
    st.sidebar.header("설정")
    
    # 분석 대상 (사용자 요청: S&P500, Nasdaq100, Dow30 기반 주요 종목)
    # 실제 구현 시에는 수백 개를 다 넣으면 속도가 느려지므로 주요 50~100개 종목 추천
    tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "NFLX", "JPM", "V", 
               "UNH", "COST", "AVGO", "ORCL", "XOM", "CVX", "PG", "JNJ", "HD", "ABBV"]
    
    sector_map = get_sector_mapping()
    
    # 데이터 로드
    with st.spinner('금융 데이터를 가져오는 중...'):
        prices = get_stock_data(tickers)
        
    # 2. YTD 수익률 기반 섹터 선별
    start_of_year = datetime.datetime(datetime.datetime.now().year, 1, 1)
    ytd_perf = {}
    
    for ticker in tickers:
        if ticker in prices.columns:
            ytd_start_price = prices.loc[prices.index >= start_of_year].iloc[0]
            current_price = prices.iloc[-1]
            perf = ((current_price[ticker] - ytd_start_price[ticker]) / ytd_start_price[ticker]) * 100
            ytd_perf[ticker] = perf

    # 섹터별 평균 수익률 계산
    sector_perf = []
    for ticker, perf in ytd_perf.items():
        sector_perf.append({"Ticker": ticker, "Sector": sector_map.get(ticker, "Etc"), "YTD": perf})
    
    df_perf = pd.DataFrame(sector_perf)
    leading_sectors = df_perf.groupby("Sector")["YTD"].mean().sort_values(ascending=False)

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📊 섹터별 YTD 성과")
        st.bar_chart(leading_sectors)

    # 3. 주도 섹터 내 상위 3개 종목
    top_sector = leading_sectors.index[0]
    st.subheader(f"🏆 현재 주도 섹터: {top_sector}")
    top_3_stocks = df_perf[df_perf["Sector"] == top_sector].sort_values(by="YTD", ascending=False).head(3)
    st.table(top_3_stocks[["Ticker", "YTD"]])

    # 4. 추천 종목: 주도 섹터 내 눌림목 기업 (3종목)
    st.subheader("🔍 주도 섹터 내 눌림목 추천 종목")
    st.write("기준: 주봉 이평선(20/50/100) 근접 & 50일선 정배열 유지")

    recommendations = []
    
    for ticker in df_perf[df_perf["Sector"].isin(leading_sectors.index[:3])]["Ticker"]:
        # 일봉 기반 50일 이평선 (정배열 확인용)
        sma_50 = prices[ticker].rolling(window=50).mean()
        # 주봉 변환 (눌림목 확인용)
        weekly_price = prices[ticker].resample('W').last()
        w_sma_20 = weekly_price.rolling(window=20).mean()
        w_sma_50 = weekly_price.rolling(window=50).mean()
        w_sma_100 = weekly_price.rolling(window=100).mean()

        curr_p = prices[ticker].iloc[-1]
        
        # 필터링 조건
        # 1. 50일 이평선 정배열(상승 중)
        is_bullish = sma_50.iloc[-1] > sma_50.iloc[-5]
        # 2. 50일선 크게 이탈하지 않음 (현재가가 50일선의 90% 이상)
        not_broken = curr_p > (sma_50.iloc[-1] * 0.95)
        
        # 3. 이평선 근접 여부 (2% 이내 근접)
        on_support = any([abs(curr_p - w_sma_20.iloc[-1])/w_sma_20.iloc[-1] < 0.02,
                          abs(curr_p - w_sma_50.iloc[-1])/w_sma_50.iloc[-1] < 0.02,
                          abs(curr_p - w_sma_100.iloc[-1])/w_sma_100.iloc[-1] < 0.02])

        if is_bullish and not_broken and on_support:
            recommendations.append({
                "Ticker": ticker,
                "YTD": f"{ytd_perf[ticker]:.2f}%",
                "1Y_DD": f"{calculate_drawdown(prices[ticker], 1):.2f}%",
                "2Y_DD": f"{calculate_drawdown(prices[ticker], 2):.2f}%",
                "3Y_DD": f"{calculate_drawdown(prices[ticker], 3):.2f}%"
            })

    if recommendations:
        st.dataframe(pd.DataFrame(recommendations).head(3))
    else:
        st.info("현재 눌림목 조건에 부합하는 주도주가 없습니다.")

if __name__ == "__main__":
    main()
