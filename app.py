# --- 결과 출력 부분 수정 ---
if performance_results:
    st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
    perf_df = pd.DataFrame(performance_results).sort_values('YTD', ascending=False).head(3)
    st.dataframe(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}), hide_index=True, use_container_width=True)

    st.divider()
    st.subheader("🎯 기술적 눌림목 추천 TOP 10 (종합 점수순)")
    
    if not recs_df.empty:
        # 출력하려는 전체 컬럼 리스트
        display_cols = [
            'Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)',
            'Market Cap', 'Sales', 'Income', 'P/E', '3Y Avg P/E', 'Forward P/E', 'PEG', 'P/S', 
            'EPS next 5Y', 'Oper.Margin', 'EPS Q/Q', 'Sales Q/Q'
        ]
        
        # KeyError 방지를 위해 .reindex() 사용 (없는 컬럼은 NaN으로 생성됨)
        final_df = recs_df.reindex(columns=display_cols)
        
        # 데이터프레임 출력
        st.dataframe(
            final_df.style.format(precision=1, na_rep='-'), 
            hide_index=True, 
            use_container_width=True
        )
    else:
        st.info("조건을 만족하는 눌림목 종목이 없습니다.")
import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 1. Page Configuration
st.set_page_config(page_title="Market Alpha Hunter", layout="wide")

# 2. UI Styling (Right Alignment and Font adjustments)
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    /* Force right alignment for table headers and cells */
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    div[data-testid="stDataFrame"] th { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 거래량 기반 눌림목 추천")

# 3. Utility Functions for Formatting
def format_val(val, is_currency=False):
    """Formats values to 1 decimal place and adds B/M units for currency."""
    if val is None or pd.isna(val) or val == "" or val == "nan":
        return "-"
    
    try:
        num = float(val)
        if is_currency:
            abs_num = abs(num)
            if abs_num >= 1e9:
                return f"{num/1e9:.1f}B"
            elif abs_num >= 1e6:
                return f"{num/1e6:.1f}M"
            else:
                return f"{num:.1f}"
        return f"{num:.1f}"
    except (ValueError, TypeError):
        return str(val)

# 4. Date Settings (Dynamic for Year Transition)
today = datetime.now()
# For YTD calculation: Get a range around the end of last year to find the last valid trading day
last_year_start_range = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end_range = datetime(today.year, 1, 2).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')
hist_start = (today - timedelta(weeks=160)).strftime('%Y-%m-%d')

# 5. Data Scraping Functions
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

@st.cache_data(ttl=86400)
def get_dow30_list():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = 'https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average'
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_html(io.StringIO(res.text), match='Symbol')[0]
        ticker_col = 'Symbol' if 'Symbol' in df.columns else df.columns[1]
        return df[ticker_col].astype(str).str.replace('.', '-', regex=False).str.strip().tolist()
    except: return []

# 6. Sidebar UI
sp500_data = get_sp500_list()
if not sp500_data.empty:
    gics_sectors = sorted(sp500_data['GICS Sector'].unique().tolist())
    menu_options = gics_sectors + ["Nasdaq100", "Dow30"]
    selected_menu = st.sidebar.selectbox("분석 대상 선택", menu_options)
    
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
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status(f"{selected_menu} 분석 진행 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            chunk_size = 15

            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                try:
                    # YTD Base Data (Price at the end of last year)
                    ytd_base_all = yf.download(chunk, start=last_year_start_range, end=last_year_end_range, interval="1d", group_by='ticker', progress=False, session=session)
                    # Weekly Data for Technical Indicators
                    w_data_all = yf.download(chunk, start=hist_start, end=today_str, interval="1wk", group_by='ticker', progress=False, session=session)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data_all.columns.levels[0]: continue
                            w_df = w_data_all[ticker].dropna()
                            if len(w_df) < 100: continue
                            
                            # YTD Calculation
                            if ticker in ytd_base_all.columns.levels[0]:
                                t_base = ytd_base_all[ticker].dropna()
                                base_price = t_base['Close'].iloc[-1] if not t_base.empty else w_df['Close'].iloc[0]
                            else:
                                base_price = w_df['Close'].iloc[0]
                                
                            curr_p = w_df['Close'].iloc[-1]
                            ytd_ret = ((curr_p / base_price) - 1) * 100
                            
                            performance_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})

                            # Technical Indicators
                            ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                            ma50 = w_df['Close'].rolling(50).mean().iloc[-1]
                            ma100 = w_df['Close'].rolling(100).mean().iloc[-1]
                            max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                            vol_ratio = (w_df['Volume'].iloc[-1] / max_v_8w) if max_v_8w > 0 else 1.0

                            # Pullback Filter: 1) Uptrend (50>100) 2) Low Volume (<65%)
                            if (ma50 > ma100) and (vol_ratio <= 0.65):
                                dist_ma20 = abs(curr_p - ma20) / ma20 * 100
                                dist_ma50 = abs(curr_p - ma50) / ma50 * 100
                                min_dist = min(dist_ma20, dist_ma50)
                                # Scoring: Proximity(60 pts) + Volume Reduction(40 pts)
                                score = ((1 - min_dist/10) * 60) + ((1 - vol_ratio) * 40)

                                recommendation_results.append({
                                    'Ticker': ticker, 
                                    'YTD': ytd_ret, 
                                    '현재가': curr_p,
                                    '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                    '거래량비중(%)': vol_ratio * 100,
                                    '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50',
                                    '인접도': min_dist,
                                    '종합점수': max(0, score)
                                })
                        except: continue
                except: pass
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

            # --- Fundamental Deep Dive for Top 10 ---
            if recommendation_results:
                recs_df_raw = pd.DataFrame(recommendation_results).sort_values('종합점수', ascending=False).head(10)
                final_recs = []
                for _, row in recs_df_raw.iterrows():
                    t_obj = yf.Ticker(row['Ticker'])
                    info = t_obj.info
                    
                    # 3-Year Average P/E Calculation
                    try:
                        income_stmt = t_obj.income_stmt
                        if not income_stmt.empty and 'Net Income' in income_stmt.index:
                            avg_net_income = income_stmt.loc['Net Income'].head(3).mean()
                            m_cap = info.get('marketCap', 0)
                            avg_pe_3y = m_cap / avg_net_income if avg_net_income > 0 else None
                        else: avg_pe_3y = None
                    except: avg_pe_3y = None

                    # Merge technical and fundamental data
                    row.update({
                        'Market Cap': format_val(info.get('marketCap'), True),
                        'Sales': format_val(info.get('totalRevenue'), True),
                        'Income': format_val(info.get('netIncomeToCommon'), True),
                        'P/E': format_val(info.get('trailingPE')),
                        '3Y Avg P/E': format_val(avg_pe_3y),
                        'Forward P/E': format_val(info.get('forwardPE')),
                        'PEG': format_val(info.get('pegRatio')),
                        'P/S': format_val(info.get('priceToSalesTrailing12Months')),
                        'EPS next 5Y': format_val(info.get('earningsGrowth', 0) * 100),
                        'Oper.Margin': format_val(info.get('operatingMargins', 0) * 100),
                        'EPS Q/Q': format_val(info.get('earningsQuarterlyGrowth', 0) * 100),
                        'Sales Q/Q': format_val(info.get('revenueQuarterlyGrowth', 0) * 100),
                        '종합점수': format_val(row['종합점수']),
                        'YTD': format_val(row['YTD']),
                        '현재가': format_val(row['현재가']),
                        '1Y_고점대비': format_val(row['1Y_고점대비']),
                        '인접도': format_val(row['인접도']),
                        '거래량비중(%)': format_val(row['거래량비중(%)'])
                    })
                    final_recs.append(row)
                recs_df = pd.DataFrame(final_recs)
            else:
                recs_df = pd.DataFrame()

            status.update(label="분석 완료!", state="complete")

        # 7. Results Output
        if performance_results:
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(performance_results).sort_values('YTD', ascending=False).head(3)
            st.dataframe(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}), hide_index=True, use_container_width=True)

            st.divider()
            st.subheader("🎯 기술적 눌림목 추천 TOP 10 (종합 점수순)")
            
            if not recs_df.empty:
                display_cols = [
                    'Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)',
                    'Market Cap', 'Sales', 'Income', 'P/E', '3Y Avg P/E', 'Forward P/E', 'PEG', 'P/S', 
                    'EPS next 5Y', 'Oper.Margin', 'EPS Q/Q', 'Sales Q/Q'
                ]
                
                # Use reindex to safely select columns and avoid KeyError if a field is missing
                final_display_df = recs_df.reindex(columns=display_cols)
                st.dataframe(final_display_df, hide_index=True, use_container_width=True)
            else:
                st.info("현재 눌림목 조건(정배열 & 거래량 급감)을 만족하는 종목이 없습니다.")
        else:
            st.error("데이터를 불러오는 데 실패했습니다.")

else:
    st.error("S&P 500 리스트를 불러오지 못했습니다. 인터넷 연결을 확인하세요.")
