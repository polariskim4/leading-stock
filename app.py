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

# UI 스타일 개선: 모든 셀 오른쪽 정렬 및 소수점 정렬용 CSS
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    div[data-testid="stDataFrame"] th { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 거래량 기반 눌림목 추천")

# --- 유틸리티 함수: 단위 변환 (B/M) 및 소수점 한자리 ---
def format_currency(val):
    if val is None or pd.isna(val) or val == 0:
        return "-"
    abs_val = abs(val)
    if abs_val >= 1e9:
        return f"{val/1e9:.1f}B"
    if abs_val >= 1e6:
        return f"{val/1e6:.1f}M"
    return f"{val:.1f}"

def format_num(val):
    if val is None or pd.isna(val):
        return "-"
    return f"{float(val):.1f}"

# --- 1. 날짜 설정 ---
today = datetime.now()
last_year_start_range = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end_range = datetime(today.year, 1, 2).strftime('%Y-%m-%d') 
today_str = today.strftime('%Y-%m-%d')

# --- 2. 데이터 소스 가져오기 (S&P 500, Nasdaq100, Dow30) ---
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False).str.strip()
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
        return df[ticker_col].astype(str).str.replace('.', '-', regex=False).str.strip().tolist()
    except: return []

sp500_data = get_sp500_list()

if not sp500_data.empty:
    gics_sectors = sorted(sp500_data['GICS Sector'].unique().tolist())
    selected_menu = st.sidebar.selectbox("분석 대상 선택", gics_sectors + ["Nasdaq100"])
    
    if selected_menu == "Nasdaq100":
        target_tickers = get_nasdaq100_list()
    else:
        target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_menu]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상: {len(target_tickers)}개 종목")
    run_analysis = st.sidebar.button(f"{selected_menu} 분석 시작")

    if run_analysis:
        performance_results = []
        recommendation_results = []
        hist_start = (datetime.now() - timedelta(weeks=160)).strftime('%Y-%m-%d')
        session = requests.Session()

        with st.status(f"{selected_menu} 데이터 분석 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            chunk_size = 15

            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                try:
                    ytd_base_df = yf.download(chunk, start=last_year_start_range, end=last_year_end_range, interval="1d", group_by='ticker', progress=False)
                    w_data = yf.download(chunk, start=hist_start, end=today_str, interval="1wk", group_by='ticker', progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data.columns.levels[0]: continue
                            w_df = w_data[ticker].dropna()
                            t_base = ytd_base_df[ticker].dropna() if ticker in ytd_base_df.columns.levels[0] else pd.DataFrame()
                            
                            if w_df.empty or len(w_df) < 100: continue
                            
                            base_price = t_base['Close'].iloc[-1] if not t_base.empty else w_df['Close'].iloc[0]
                            curr_p = w_df['Close'].iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100
                            
                            performance_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})

                            # 눌림목 기술적 지표
                            ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                            ma50 = w_df['Close'].rolling(50).mean().iloc[-1]
                            ma100 = w_df['Close'].rolling(100).mean().iloc[-1]
                            max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                            vol_ratio = (w_df['Volume'].iloc[-1] / max_v_8w) if max_v_8w > 0 else 1.0

                            if (ma50 > ma100) and (vol_ratio <= 0.65):
                                dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                                dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                                min_dist = min(dist_ma20, dist_ma50)
                                score = ((1 - min_dist/10) * 60) + ((1 - vol_ratio) * 40)

                                recommendation_results.append({
                                    'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                    '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                    '거래량비중(%)': vol_ratio * 100,
                                    '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50',
                                    '인접도': min_dist,
                                    '종합점수': max(0, score)
                                })
                        except: continue
                except: pass
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

            # --- 상위 10개 종목 펀더멘털 및 3년 평균 P/E 수집 ---
            if recommendation_results:
                recs_df_raw = pd.DataFrame(recommendation_results).sort_values('종합점수', ascending=False).head(10)
                final_list = []
                for _, row in recs_df_raw.iterrows():
                    t_obj = yf.Ticker(row['Ticker'])
                    info = t_obj.info
                    
                    # 3년 평균 P/E 계산 로직 (수동 계산으로 데이터 누락 방지)
                    try:
                        income = t_obj.income_stmt
                        if not income.empty and 'Net Income' in income.index:
                            net_income_3y = income.loc['Net Income'].head(3).mean()
                            m_cap = info.get('marketCap', 0)
                            avg_pe_3y = m_cap / net_income_3y if net_income_3y > 0 else None
                        else: avg_pe_3y = None
                    except: avg_pe_3y = None

                    row.update({
                        'Market Cap': format_currency(info.get('marketCap')),
                        'Sales': format_currency(info.get('totalRevenue')),
                        'Income': format_currency(info.get('netIncomeToCommon')),
                        'P/E': format_num(info.get('trailingPE')),
                        '3Y Avg P/E': format_num(avg_pe_3y),
                        'Forward P/E': format_num(info.get('forwardPE')),
                        'PEG': format_num(info.get('pegRatio')),
                        'P/S': format_num(info.get('priceToSalesTrailing12Months')),
                        'EPS next 5Y': format_num(info.get('earningsGrowth', 0) * 100),
                        'Oper.Margin': format_num(info.get('operatingMargins', 0) * 100),
                        'EPS Q/Q': format_num(info.get('earningsQuarterlyGrowth', 0) * 100),
                        'Sales Q/Q': format_num(info.get('revenueQuarterlyGrowth', 0) * 100),
                        '종합점수': format_num(row['종합점수']),
                        '1Y_고점대비': format_num(row['1Y_고점대비']),
                        '인접도': format_num(row['인접도']),
                        '거래량비중(%)': format_num(row['거래량비중(%)'])
                    })
                    final_list.append(row)
                recs_df = pd.DataFrame(final_list)
            else: recs_df = pd.DataFrame()

            status.update(label="분석 완료!", state="complete")

        # --- 결과 출력 ---
        if performance_results:
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(performance_results).sort_values('YTD', ascending=False).head(3)
            st.dataframe(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}), hide_index=True, use_container_width=True)

            st.divider()
            st.subheader("🎯 기술적 눌림목 추천 TOP 10 (종합 점수순)")
            if not recs_df.empty:
                # 컬럼 순서 재배치
                display_cols = [
                    'Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)',
                    'Market Cap', 'Sales', 'Income', 'P/E', '3Y Avg P/E', 'Forward P/E', 'PEG', 'P/S', 
                    'EPS next 5Y', 'Oper.Margin', 'EPS Q/Q', 'Sales Q/Q'
                ]
                st.dataframe(recs_df[display_cols], hide_index=True, use_container_width=True)
            else:
                st.info("조건을 만족하는 눌림목 종목이 없습니다.")

