import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import requests

# --- 페이지 설정 ---
st.set_page_config(page_title="S&P 500 주도주 분석기", layout="wide")

@st.cache_data(ttl=3600)
def get_sp500_tickers():
    """위키피디아에서 S&P 500 리스트를 안전하게 가져오기"""
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    # 브라우저인 것처럼 헤더 설정 (403 에러 방지)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers)
        # response.text를 직접 전달하여 문자열임을 명시
        df = pd.read_html(response.text)[0]
        
        # Yahoo Finance 호환을 위해 티커의 '.'을 '-'로 변경 (예: BRK.B -> BRK-B)
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False)
        return df[['Symbol', 'GICS Sector']]
    except Exception as e:
        st.error(f"종목 리스트 로드 실패: {e}")
        return pd.DataFrame(columns=['Symbol', 'GICS Sector'])

def calculate_drawdown(series, years):
    """최근 n년 고점 대비 하락률 계산"""
    days = int(252 * years)
    if len(series) < days:
        days = len(series)
    window_data = series.tail(days)
    peak = window_data.max()
    current = series.iloc[-1]
    return ((current - peak) / peak) * 100

def normalize(series):
    """점수 산출을 위한 정규화 (0~100)"""
    if series.max() == series.min():
        return 100.0
    return (series - series.min()) / (series.max() - series.min()) * 100

def main():
    st.title("🚀 S&P 500 주도 섹터 및 눌림목 분석")
    
    # 1. 티커 리스트 가져오기
    sector_info = get_sp500_tickers()
    if sector_info.empty:
        st.warning("데이터를 불러올 수 없습니다. 잠시 후 다시 시도해주세요.")
        return

    # 성능을 위해 상위 100개 종목 우선 분석 (필요시 조절 가능)
    tickers = sector_info['Symbol'].tolist()[:100]

    # 2. 주가 데이터 다운로드
    with st.spinner('실시간 시장 데이터를 분석 중입니다...'):
        data = yf.download(tickers, period="2y", interval="1d", progress=False)
        if data.empty:
            st.error("Yahoo Finance에서 데이터를 가져오지 못했습니다.")
            return
        
        close_prices = data['Close']
        volumes = data['Volume']

    # 3. 섹터 성과 분석 (YTD 기준)
    start_of_year = datetime.datetime(datetime.datetime.now().year, 1, 1)
    ytd_prices = close_prices.loc[close_prices.index >= start_of_year]
    
    if not ytd_prices.empty:
        ytd_returns = ((close_prices.iloc[-1] / ytd_prices.iloc[0]) - 1) * 100
    else:
        ytd_returns = pd.Series(0, index=tickers)

    sector_info['YTD'] = sector_info['Symbol'].map(ytd_returns)
    sector_perf = sector_info.groupby('GICS Sector')['YTD'].mean().sort_values(ascending=False)

    st.subheader("📊 섹터별 YTD 수익률 현황")
    st.bar_chart(sector_perf)

    # 4. 눌림목 종목 선별 및 점수화
    st.divider()
    st.subheader("🔍 주도 섹터 내 눌림목 추천 (TOP 10)")

    top_sectors = sector_perf.index[:3].tolist() # 상위 3개 섹터 대상
    pullback_candidates = []

    for ticker in tickers:
        if ticker not in close_prices.columns: continue
        
        row_sector = sector_info[sector_info['Symbol'] == ticker]['GICS Sector'].values[0]
        if row_sector not in top_sectors: continue

        series = close_prices[ticker].dropna()
        if len(series) < 150: continue

        # 이동평균선 계산
        sma50 = series.rolling(window=50).mean()
        weekly_series = series.resample('W').last()
        wsma20 = weekly_series.rolling(window=20).mean().iloc[-1]
        wsma50 = weekly_series.rolling(window=50).mean().iloc[-1]
        wsma100 = weekly_series.rolling(window=100).mean().iloc[-1]
        
        curr_price = series.iloc[-1]

        # 조건 1: 50일선 정배열(상승 중)
        is_bullish = sma50.iloc[-1] > sma50.iloc[-10]
        # 조건 2: 50일선 근처 유지 (크게 이탈하지 않음)
        not_broken = curr_price > (sma50.iloc[-1] * 0.95)
        # 조건 3: 주봉 이평선(20, 50, 100) 중 하나에 3% 이내 근접
        support_levels = [wsma20, wsma50, wsma100]
        on_support = any([abs(curr_price - ma) / ma < 0.03 for ma in support_levels if not pd.isna(ma)])

        if is_bullish and not_broken and on_support:
            # 점수 산출용 지표
            sma_ratio = curr_price / sma50.iloc[-1]
            vol_ratio = volumes[ticker].iloc[-1] / volumes[ticker].tail(20).mean()
            
            pullback_candidates.append({
                'Ticker': ticker,
                'Sector': row_sector,
                'Price': round(curr_price, 2),
                'YTD': f"{ytd_returns[ticker]:.2f}%",
                '1Y_DD': round(calculate_drawdown(series, 1), 2),
                '2Y_DD': round(calculate_drawdown(series, 2), 2),
                '3Y_DD': round(calculate_drawdown(series, 3), 2),
                'sma_ratio': sma_ratio,
                'vol_ratio': vol_ratio
            })

    if pullback_candidates:
        res_df = pd.DataFrame(pullback_candidates)
        # 가중치 적용 (SMA 70%, 거래량 30%)
        res_df['Score'] = (normalize(res_df['sma_ratio']) * 0.7) + (normalize(res_df['vol_ratio']) * 0.3)
        
        final_display = res_df.sort_values(by='Score', ascending=False).head(10)
        st.dataframe(
            final_display[['Ticker', 'Sector', 'Price', 'YTD', '1Y_DD', '2Y_DD', '3Y_DD', 'Score']],
            use_container_width=True, hide_index=True
        )
    else:
        st.info("현재 눌림목 조건에 맞는 주도주가 없습니다.")

if __name__ == "__main__":
    main()
