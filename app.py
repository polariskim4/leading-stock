# 이 줄을 삭제하거나 앞에 #을 붙여 주석 처리하세요.
# from pandas_datareader import data as pdr 
import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

# --- Configuration & Styling ---
st.set_page_config(page_title="주도주 눌림목 분석기", layout="wide")

@st.cache_data(ttl=3600)
def get_stock_list():
    """S&P 500 종목 및 섹터 정보 가져오기"""
    try:
        url = '<https://en.wikipedia.org/wiki/List_of_S%26P_500_companies>'
        table = pd.read_html(url)
        df = table[0]
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"종목 리스트 로드 실패: {e}")
        return pd.DataFrame(columns=['Symbol', 'GICS Sector'])

def calculate_drawdown(series, years):
    """특정 기간 고점 대비 하락률 계산"""
    days = int(252 * years)
    if len(series) < days:
        days = len(series)
    window_data = series.tail(days)
    peak = window_data.max()
    current = series.iloc[-1]
    return ((current - peak) / peak) * 100

def normalize(series):
    """점수 합산을 위한 0-100 정규화"""
    if series.max() == series.min():
        return 100.0
    return (series - series.min()) / (series.max() - series.min()) * 100

# --- Main Logic ---
def main():
    st.title("🚀 Leading Sector Pullback Analyzer")
    st.markdown("S&P500 주도 섹터 분석 및 주봉 이평선 기반 눌림목 종목 선별")

    # 1. 데이터 준비
    sector_info = get_stock_list()
    # 속도와 안정성을 위해 상위 시총/주요 종목 100개 위주 분석 (필요시 조절)
    tickers = sector_info['Symbol'].str.replace('.', '-', regex=False).tolist()[:100]

    with st.spinner('시장 데이터를 분석 중입니다...'):
        # YTD 및 이평선 계산을 위한 데이터 로드 (최근 2년치)
        data = yf.download(tickers, period="2y", interval="1d", progress=False)
        close_prices = data['Close']
        volumes = data['Volume']

    if close_prices.empty:
        st.error("데이터를 가져오지 못했습니다. 잠시 후 다시 시도해주세요.")
        return

    # 2. 섹터별 YTD 성과 계산
    start_of_year = datetime.datetime(datetime.datetime.now().year, 1, 1)
    ytd_prices = close_prices.loc[close_prices.index >= start_of_year]
    
    if ytd_prices.empty:
        ytd_returns = pd.Series(0, index=tickers)
    else:
        ytd_returns = ((close_prices.iloc[-1] / ytd_prices.iloc[0]) - 1) * 100

    sector_info['YTD'] = sector_info['Symbol'].map(ytd_returns)
    sector_perf = sector_info.groupby('GICS Sector')['YTD'].mean().sort_values(ascending=False)

    # 3. 주도 섹터 표시
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("📊 섹터별 YTD 수익률")
        st.bar_chart(sector_perf)

    top_sectors = sector_perf.index[:3].tolist()
    with col2:
        st.subheader(f"🏆 TOP 3 주도 섹터")
        for i, s in enumerate(top_sectors):
            st.write(f"**{i+1}위: {s}** ({sector_perf[s]:.2f}%)")

    # 4. 눌림목 필터링 및 종합 점수 계산
    st.divider()
    st.subheader("🔍 주도 섹터 내 눌림목 추천 종목 (TOP 10)")

    pullback_results = []
    
    # 주도 섹터에 속하는 종목들 필터링
    target_tickers = sector_info[sector_info['GICS Sector'].isin(top_sectors)]['Symbol'].tolist()

    for ticker in target_tickers:
        if ticker not in close_prices.columns: continue
        
        series = close_prices[ticker].dropna()
        if len(series) < 100: continue

        # [일봉] 50일 이평선 및 추세
        sma50 = series.rolling(window=50).mean()
        curr_price = series.iloc[-1]
        
        # [주봉] 이평선 계산
        weekly_series = series.resample('W').last()
        wsma20 = weekly_series.rolling(window=20).mean().iloc[-1]
        wsma50 = weekly_series.rolling(window=50).mean().iloc[-1]
        wsma100 = weekly_series.rolling(window=100).mean().iloc[-1]

        # --- 필터링 조건 (어제 버전 유지) ---
        # 1. 50일 이평선 정배열(상향) 확인
        is_bullish = sma50.iloc[-1] > sma50.iloc[-5]
        # 2. 50일 이평선 크게 이탈 제외 (현재가가 50일선의 95% 이상)
        not_broken = curr_price > (sma50.iloc[-1] * 0.95)
        # 3. 주봉 이평선(20, 50, 100) 중 하나에 근접 (3% 이내)
        on_support = any([abs(curr_price - ma) / ma < 0.03 for ma in [wsma20, wsma50, wsma100] if not pd.isna(ma)])

        if is_bullish and not_broken and on_support:
            # 점수 산출용 지표
            sma_ratio = curr_price / sma50.iloc[-1]
            avg_vol = volumes[ticker].tail(20).mean()
            vol_ratio = volumes[ticker].iloc[-1] / avg_vol if avg_vol > 0 else 1
            
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
        
        # 가중치 점수 계산 (SMA 70%, 거래량 30%)
        res_df['SMA_Score'] = normalize(res_df['sma_ratio'])
        res_df['Vol_Score'] = normalize(res_df['vol_ratio'])
        res_df['Total_Score'] = (res_df['SMA_Score'] * 0.7) + (res_df['Vol_Score'] * 0.3)
        
        # 정렬 및 10개 추출
        final_df = res_df.sort_values(by='Total_Score', ascending=False).head(10)
        
        # 최종 디스플레이 (요청한 컬럼 구성)
        display_cols = ['Ticker', 'Sector', 'Price', 'YTD', '1Y_DD', '2Y_DD', '3Y_DD', 'Total_Score']
        st.dataframe(final_df[display_cols].reset_index(drop=True), use_container_width=True)
    else:
        st.info("현재 눌림목 조건에 부합하는 종목이 없습니다.")

if __name__ == "__main__":
    main()
# 이 줄을 삭제하거나 앞에 #을 붙여 주석 처리하세요.
# from pandas_datareader import data as pdr 
