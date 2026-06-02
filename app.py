import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import time
import random
from datetime import datetime, timedelta

# 1. 페이지 설정 및 UI 스타일
st.set_page_config(page_title="Market Alpha Hunter", layout="wide")

st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    div[data-testid="stDataFrame"] th { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 거래량 기반 눌림목 추천")

# 2. 유틸리티 함수: 포맷팅 및 단위 변환
def format_val(val, is_currency=False):
    if val is None or pd.isna(val) or val == "" or val == "nan" or val == 0:
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

# 3. 날짜 설정
today = datetime.now()
last_year_start_range = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end_range = datetime(today.year, 1, 2).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')
hist_start = (today - timedelta(weeks=160)).strftime('%Y-%m-%d')

# 4. 데이터 소스 가져오기
@st.cache_data(ttl=86400)
def get_sp500_list():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
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
    menu_options = gics_sectors + ["Nasdaq100"]
    selected_menu = st.sidebar.selectbox("분석 대상 선택", menu_options)
    
    if selected_menu == "Nasdaq100":
        target_tickers = get_nasdaq100_list()
    else:
        target_tickers = sp500_data[sp500_data['GICS Sector'] == selected_menu]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상: {len(target_tickers)}개 종목")
    run_analysis = st.sidebar.button(f"{selected_menu} 분석 시작")

    if run_analysis:
        performance_results = []
        recommendation_results = []
        
        # Yahoo Finance 차단 방지를 위한 세션 설정
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'})

        with st.status(f"{selected_menu} 분석 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            chunk_size = 15

            for i in range(0, len(target_tickers), chunk_size):
                chunk = target_tickers[i:i + chunk_size]
                try:
                    ytd_base_all = yf.download(chunk, start=last_year_start_range, end=last_year_end_range, interval="1d", group_by='ticker', progress=False, session=session)
                    w_data_all = yf.download(chunk, start=hist_start, end=today_str, interval="1wk", group_by='ticker', progress=False, session=session)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_data_all.columns.levels[0]: continue
                            w_df = w_data_all[ticker].dropna()
                            if len(w_df) < 100: continue
                            
                            if ticker in ytd_base_all.columns.levels[0]:
                                t_base = ytd_base_all[ticker].dropna()
                                base_p = t_base['Close'].iloc[-1] if not t_base.empty else w_df['Close'].iloc[0]
                            else: base_p = w_df['Close'].iloc[0]
                                
                            curr_p = w_df['Close'].iloc[-1]
                            ytd_ret = ((curr_p / base_p) - 1) * 100
                            performance_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})

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
                                    '인접도': min_dist, '종합점수': max(0, score)
                                })
                        except: continue
                except: pass
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

            # --- 상위 10개 종목 재무 데이터 정밀 수집 ---
            final_recs_list = []
            if recommendation_results:
                recs_df_raw = pd.DataFrame(recommendation_results).sort_values('종합점수', ascending=False).head(10)
                for _, row in recs_df_raw.iterrows():
                    ticker = row['Ticker']
                    t_obj = yf.Ticker(ticker, session=session)
                    
                    # 데이터 안정성 확보를 위해 여러 소스 시도
                    info = t_obj.info if t_obj.info else {}
                    fast = t_obj.fast_info
                    income_stmt = t_obj.income_stmt
                    
                    # Sales, Income은 재무제표에서 직접 추출 (더 정확함)
                    sales = income_stmt.loc['Total Revenue'].iloc[0] if not income_stmt.empty and 'Total Revenue' in income_stmt.index else info.get('totalRevenue')
                    net_income = income_stmt.loc['Net Income'].iloc[0] if not income_stmt.empty and 'Net Income' in income_stmt.index else info.get('netIncomeToCommon')

                    # 3년 평균 P/E 계산
                    try:
                        if not income_stmt.empty and 'Net Income' in income_stmt.index:
                            avg_ni = income_stmt.loc['Net Income'].head(3).mean()
                            m_cap = fast.get('market_cap', info.get('marketCap', 0))
                            avg_pe_3y = m_cap / avg_ni if avg_ni > 0 else None
                        else: avg_pe_3y = None
                    except: avg_pe_3y = None

                    row.update({
                        'Market Cap': format_val(fast.get('market_cap', info.get('marketCap')), True),
                        'Sales': format_val(sales, True),
                        'Income': format_val(net_income, True),
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
                        '1Y_고점대비': format_val(row['1Y_고점대비']),
                        '인접도': format_val(row['인접도']),
                        '거래량비중(%)': format_val(row['거래량비중(%)'])
                    })
                    final_recs_list.append(row)
            
            status.update(label="분석 완료!", state="complete")

        # --- 결과 출력 ---
        if performance_results:
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(performance_results).sort_values('YTD', ascending=False).head(3)
            st.dataframe(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}), hide_index=True, use_container_width=True)

            st.divider()
            st.subheader("🎯 기술적 눌림목 추천 TOP 10 (종합 점수순)")
            if final_recs_list:
                recs_df = pd.DataFrame(final_recs_list)
                display_cols = [
                    'Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)',
                    'Market Cap', 'Sales', 'Income', 'P/E', '3Y Avg P/E', 'Forward P/E', 'PEG', 'P/S', 
                    'EPS next 5Y', 'Oper.Margin', 'EPS Q/Q', 'Sales Q/Q'
                ]
                final_display = recs_df.reindex(columns=display_cols)
                st.dataframe(final_display, hide_index=True, use_container_width=True)
            else:
                st.info("조건을 만족하는 눌림목 종목이 없습니다.")
