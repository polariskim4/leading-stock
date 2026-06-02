import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import requests

# --- 페이지 설정 ---
st.set_page_config(page_title="S&P 500 주도주 눌림목 분석기", layout="wide")

@st.cache_data(ttl=3600)
def get_sp500_tickers():
    """위키피디아에서 S&P 500 종목 및 섹터 정보 가져오기 (403 에러 방지 포함)"""
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers)
        df = pd.read_html(response.text)[0]
        # Yahoo Finance 호환을 위해 점(.)을 하이픈(-)으로 변경 (예: BRK.B -> BRK-B)
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False)
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"종목 리스트 로드 실패: {e}")
        return pd.DataFrame(columns=['Symbol', 'GICS Sector'])

def calculate_drawdown(series, years):
    """특정 기간 고점 대비 하락률(Drawdown) 계산"""
    days = int(252 * years)
    if len(series) < days:
        days = len(series)
    window_data = series.tail(days)
    peak = window_data.max()
    current = series.iloc[-1]
    return ((current - peak) / peak) * 100

def normalize(series):
    """0-100 정규화 스코어링"""
    if series.max() == series.min():
        return 100.0
    return (series - series.min()) / (series.max() - series.min()) * 100

def main():
    st.title("🚀 S&P 500 주도 섹터 및 눌림목 주도주 분석")
    
    # 1. 종목 리스트 확보
    sector_info = get_sp500_tickers()
    if sector_info.empty:
        st.stop() # 리스트 없으면 중단

    # 분석 속도를 위해 시가총액 상위 위주로 샘플링하거나 전체 분석 가능
    tickers = sector_info['Symbol'].tolist()[:150] # 상위 150개 종목 우선 분석

    # 2. 데이터 다운로드
    with st.spinner('시장 데이터를 다운로드 중입니다... (약 10~20초 소요)'):
        # ValueError 방지를 위해 티커 존재 여부 확인
        if not tickers:
            st.error("티커 리스트가 비어 있습니다.")
            st.stop()
            
        data = yf.download(tickers, period="2y", interval="1d", progress=False)
        close_prices = data['Close']
        volumes = data['Volume']

    if close_prices.empty:
        st.error("주가 데이터를 가져오지 못했습니다.")
        st.stop()

    # 3. YTD 및 섹터 분석
    start_of_year = datetime.datetime(datetime.datetime.now().year, 1, 1)
    ytd_data = close_prices.loc[close_prices.index >= start_of_year]
    
    if not ytd_data.empty:
        ytd_returns = ((close_prices.iloc[-1] / ytd_data.iloc[0]) - 1) * 100
    else:
        ytd_returns = pd.Series(0, index=close_prices.columns)

    sector_info['YTD'] = sector_info['Symbol'].map(ytd_returns)
    sector_perf = sector_info.groupby('GICS Sector')['YTD'].mean().sort_values(ascending=False)

    # 섹터 성과 시각화
    st.subheader("📊 섹터별 YTD 수익률")
    st.bar_chart(sector_perf)

    # 4. 눌림목 필터링 로직
    st.divider()
    st.subheader("🔍 주도 섹터 내 눌림목 추천 종목 (TOP 10)")
    
    # 상위 3개 주도 섹터 선정
    top_sectors = sector_perf.index[:3].tolist()
    target_tickers = sector_info[sector_info['GICS Sector'].isin(top_sectors)]['Symbol'].tolist()

    pullback_results = []
    
    for ticker in target_tickers:
        if ticker not in close_prices.columns: continue
        
        series = close_prices[ticker].dropna()
        if len(series) < 150: continue

        # [일봉] 50일 SMA 및 추세 필터
        sma50 = series.rolling(window=50).mean()
        curr_price = series.iloc[-1]
        
        # [주봉] 변환 및 이평선 (20, 50, 100)
        weekly_series = series.resample('W').last()
        wsma20 = weekly_series.rolling(window=20).mean().iloc[-1]
        wsma50 = weekly_series.rolling(window=50).mean().iloc[-1]
        wsma100 = weekly_series.rolling(window=100).mean().iloc[-1]

        # 필터 조건: 
        # 1. 50일선 정배열(상승세) 
        # 2. 50일선 크게 이탈하지 않음 (50일선의 95% 이상 유지)
        # 3. 주봉 20/50/100일선 중 하나에 3% 이내 근접
        is_bullish = sma50.iloc[-1] > sma50.iloc[-10]
        not_broken = curr_price > (sma50.iloc[-1] * 0.95)
        
        support_levels = [wsma20, wsma50, wsma100]
        on_support = any([abs(curr_price - ma) / ma < 0.03 for ma in support_levels if not pd.isna(ma)])

        if is_bullish and not_broken and on_support:
            # 점수 산출 지표: SMA 이격도 및 최근 거래량 비율
            sma_ratio = curr_price / sma50.iloc[-1]
            vol_ratio = volumes[ticker].iloc[-1] / volumes[ticker].tail(20).mean()
            
            pullback_results.append({
                'Ticker': ticker,
                'Sector': sector_info[sector_info['Symbol'] == ticker]['GICS Sector'].values[0],
                'Price': round(curr_price, 2),
                'YTD': round(ytd_returns.get(ticker, 0), 2),
                '1Y_DD': round(calculate_drawdown(series, 1), 2),
                '2Y_DD': round(calculate_drawdown(series, 2), 2),
                '3Y_DD': round(calculate_drawdown(series, 3), 2),
                'sma_ratio': sma_ratio,
                'vol_ratio': vol_ratio
            })

    if pullback_results:
        res_df = pd.DataFrame(pullback_results)
        # 70% SMA / 30% Volume 가중치 적용
        res_df['Total_Score'] = (normalize(res_df['sma_ratio']) * 0.7) + (normalize(res_df['vol_ratio']) * 0.3)
        
        final_df = res_df.sort_values(by='Total_Score', ascending=False).head(10)
        
        st.dataframe(
            final_df[['Ticker', 'Sector', 'Price', 'YTD', '1Y_DD', '2Y_DD', '3Y_DD', 'Total_Score']],
            use_container_width=True, hide_index=True
        )
    else:
        st.info("현재 조건에 맞는 눌림목 종목이 없습니다.")

if __name__ == "__main__":
    main()
