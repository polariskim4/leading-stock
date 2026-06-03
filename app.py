import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import io
import time
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

st.title("📈 섹터 주도주 분석 및 펀더멘털 기반 눌림목 추천")

# 2. 유틸리티 함수
def format_to_one_decimal(val):
    if val is None or val == '-' or val == "" or str(val).lower() == 'nan':
        return "-"
    suffix = ""
    text = str(val).replace(',', '').replace('$', '').strip()
    if text.endswith('%'):
        suffix = '%'
        text = text[:-1]
    elif len(text) > 1 and text[-1].upper() in ['T', 'B', 'M', 'K']:
        suffix = text[-1].upper()
        text = text[:-1]
    try:
        num = float(text)
        return f"{num:.1f}{suffix}"
    except ValueError:
        return val

def parse_market_cap(cap_str):
    if not cap_str or cap_str == '-': return 0
    multiplier = 1
    clean_str = str(cap_str).replace(',', '').replace('$', '').strip()
    if 'T' in clean_str: multiplier = 1e12
    elif 'B' in clean_str: multiplier = 1e9
    elif 'M' in clean_str: multiplier = 1e6
    try:
        numeric_part = ''.join(c for c in clean_str if c.isdigit() or c == '.')
        return float(numeric_part) * multiplier
    except: return 0

# 3. Finviz 스크래핑
def get_finviz_fundamentals(ticker):
    url = f"https://finviz.com/quote.ashx?t={ticker.upper()}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', class_='snapshot-table2')
        if not table: return None
        cells = table.find_all('td')
        temp_dict = {cells[i].text.strip(): cells[i+1].text.strip() for i in range(0, len(cells), 2)}
        return {
            "Market Cap": format_to_one_decimal(temp_dict.get("Market Cap", "-")),
            "Sales": format_to_one_decimal(temp_dict.get("Sales", "-")),
            "Income": format_to_one_decimal(temp_dict.get("Income", "-")),
            "P/E": format_to_one_decimal(temp_dict.get("P/E", "-")),
            "Forward P/E": format_to_one_decimal(temp_dict.get("Forward P/E", "-")),
            "PEG": format_to_one_decimal(temp_dict.get("PEG", "-")),
            "P/S": format_to_one_decimal(temp_dict.get("P/S", "-")),
            "EPS next 5Y": format_to_one_decimal(temp_dict.get("EPS next 5Y", "-")),
            "Oper. Margin": format_to_one_decimal(temp_dict.get("Oper. Margin", "-")),
            "EPS Q/Q": format_to_one_decimal(temp_dict.get("EPS Q/Q", "-")),
            "Sales Q/Q": format_to_one_decimal(temp_dict.get("Sales Q/Q", "-"))
        }
    except: return None

# 4. 개별 종목 분석 함수 (실시간 검색용)
def analyze_single_ticker(ticker, y_start, h_start, today_end):
    try:
        ytd_df = yf.download(ticker, start=y_start, end=today_end, interval="1d", progress=False)
        w_df = yf.download(ticker, start=h_start, interval="1wk", progress=False).dropna()
        if len(w_df) < 100: return None
        
        curr_p = w_df['Close'].iloc[-1]
        base_p = ytd_df['Close'].iloc[-1] if not ytd_df.empty else w_df['Close'].iloc[0]
        ytd_ret = ((curr_p / base_p) - 1) * 100
        
        ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
        ma50 = w_df['Close'].rolling(50).mean().iloc[-1]
        ma100 = w_df['Close'].rolling(100).mean().iloc[-1]
        max_v_8w = w_df['Volume'].iloc[-8:-1].max()
        vol_ratio = (w_df['Volume'].iloc[-1] / max_v_8w) if max_v_8w > 0 else 1.0
        
        dist20, dist50 = abs(curr_p - ma20)/ma20 * 100, abs(curr_p - ma50)/ma50 * 100
        min_dist = min(dist20, dist50)
        score = max(0, (1 - min_dist/10)*60 + (1 - vol_ratio)*40)
        
        f_data = get_finviz_fundamentals(ticker)
        if not f_data: return None
        
        avg_pe = "-"
        try:
            t_obj = yf.Ticker(ticker)
            income = t_obj.income_stmt if not t_obj.income_stmt.empty else t_obj.financials
            if not income.empty:
                ni_row = income.loc[income.index.str.contains('Net Income', case=False, na=False)]
                if not ni_row.empty:
                    avg_ni = ni_row.iloc[0].head(3).mean()
                    m_cap_val = parse_market_cap(f_data['Market Cap'])
                    if avg_ni > 0: avg_pe = m_cap_val / avg_ni
        except: pass
        
        res = {
            'Ticker': ticker.upper(), '종합점수': float(format_to_one_decimal(score)),
            '현재가': float(format_to_one_decimal(curr_p)), 'YTD': f"{format_to_one_decimal(ytd_ret)}%",
            '1Y_고점대비': f"{format_to_one_decimal(((curr_p / w_df['Close'].tail(52).max()) - 1) * 100)}%",
            '인접SMA': 'SMA 20' if dist20 < dist50 else 'SMA 50',
            '인접도': float(format_to_one_decimal(min_dist)), 
            '거래량비중(%)': f"{format_to_one_decimal(vol_ratio * 100)}%",
            '3Y Avg P/E': format_to_one_decimal(avg_pe)
        }
        res.update(f_data)
        return res
    except: return None

# 5. 데이터 소스 (위키피디아)
@st.cache_data(ttl=86400)
def get_ticker_source(market_type):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        if market_type == "Nasdaq100":
            url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            df = pd.read_html(io.StringIO(requests.get(url, headers=headers).text), match='Ticker')[0]
            ticker_col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
            return df[ticker_col].astype(str).str.replace('.', '-', regex=False).tolist()
        else:
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            return pd.read_html(io.StringIO(requests.get(url, headers=headers).text), match='Symbol')[0]
    except: return pd.DataFrame()

# 6. 메인 로직
today = datetime.now()
y_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
today_end = datetime(today.year, 1, 2).strftime('%Y-%m-%d')
h_start = (today - timedelta(weeks=160)).strftime('%Y-%m-%d')

sp500_raw = get_ticker_source("SP500")
if not sp500_raw.empty:
    sectors = sorted(sp500_raw['GICS Sector'].unique().tolist())
    selected_menu = st.sidebar.selectbox("분석 대상 선택", sectors + ["Nasdaq100"])
    target_tickers = get_ticker_source("Nasdaq100") if selected_menu == "Nasdaq100" else sp500_raw[sp500_raw['GICS Sector'] == selected_menu]['Symbol'].tolist()

    if 'analysis_results' not in st.session_state: st.session_state.analysis_results = None
    if 'perf_summary' not in st.session_state: st.session_state.perf_summary = None

    if st.sidebar.button("분석 시작"):
        candidates, perf_results = [], []
        with st.status("실시간 분석 중...", expanded=True) as status:
            p_bar = st.progress(0)
            for i in range(0, len(target_tickers), 15):
                chunk = target_tickers[i:i + 15]
                try:
                    ytd_all = yf.download(chunk, start=y_start, end=today_end, interval="1d", group_by='ticker', progress=False)
                    w_all = yf.download(chunk, start=h_start, interval="1wk", group_by='ticker', progress=False)
                    for ticker in chunk:
                        try:
                            if ticker not in w_all.columns.levels[0]: continue
                            w_df = w_all[ticker].dropna()
                            if len(w_df) < 100: continue
                            curr_p = w_df['Close'].iloc[-1]
                            base_p = ytd_all[ticker]['Close'].iloc[-1] if ticker in ytd_all.columns.levels[0] and not ytd_all[ticker].empty else w_df['Close'].iloc[0]
                            ytd_ret = ((curr_p / base_p) - 1) * 100
                            perf_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})
                            ma50, ma100 = w_df['Close'].rolling(50).mean().iloc[-1], w_df['Close'].rolling(100).mean().iloc[-1]
                            max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                            vol_ratio = (w_df['Volume'].iloc[-1] / max_v_8w) if max_v_8w > 0 else 1.0
                            if ma50 > ma100 and vol_ratio <= 0.65:
                                ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                                dist20, dist50 = abs(curr_p - ma20)/ma20 * 100, abs(curr_p - ma50)/ma50 * 100
                                candidates.append({'Ticker': ticker, '종합점수': max(0, (1 - min(dist20, dist50)/10)*60 + (1 - vol_ratio)*40), '현재가': curr_p, 'YTD': ytd_ret, '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100, '인접SMA': 'SMA 20' if dist20 < dist50 else 'SMA 50', '인접도': min(dist20, dist50), '거래량비중(%)': vol_ratio * 100})
                        except: continue
                except: pass
                p_bar.progress(min((i + 15) / len(target_tickers), 1.0))
            
            final_recs = []
            if candidates:
                status.update(label="재무 지표 수집 중...", state="running")
                top_10 = pd.DataFrame(candidates).sort_values('종합점수', ascending=False).head(10)
                for _, row in top_10.iterrows():
                    f_data = get_finviz_fundamentals(row['Ticker'])
                    if f_data:
                        avg_pe = "-"
                        try:
                            t_obj = yf.Ticker(row['Ticker'])
                            income = t_obj.income_stmt if not t_obj.income_stmt.empty else t_obj.financials
                            if not income.empty:
                                ni_row = income.loc[income.index.str.contains('Net Income', case=False, na=False)]
                                if not ni_row.empty:
                                    avg_ni = ni_row.iloc[0].head(3).mean()
                                    m_cap_val = parse_market_cap(f_data['Market Cap'])
                                    if avg_ni > 0: avg_pe = m_cap_val / avg_ni
                        except: pass
                        r_dict = row.to_dict()
                        r_dict.update(f_data)
                        r_dict['3Y Avg P/E'] = format_to_one_decimal(avg_pe)
                        for k in ['종합점수', '현재가', 'YTD', '1Y_고점대비', '인접도', '거래량비중(%)']:
                            if k in r_dict:
                                fmt = format_to_one_decimal(r_dict[k])
                                r_dict[k] = f"{fmt}%" if k in ['YTD', '1Y_고점대비', '거래량비중(%)'] else float(fmt)
                        final_recs.append(r_dict)
                    time.sleep(0.2)
            st.session_state.analysis_results, st.session_state.perf_summary = final_recs, perf_results
            status.update(label="분석 완료!", state="complete")

    # --- 결과 출력 ---
    if st.session_state.perf_summary:
        st.divider()
        st.subheader("🎯 기술적 눌림목 추천 TOP 10 (종합 점수순)")
        if st.session_state.analysis_results:
            df = pd.DataFrame(st.session_state.analysis_results)
            search_ticker = st.text_input("분석 및 강조할 티커 입력 (예: TSLA):", "").upper()
            
            # 검색 티커가 리스트에 없으면 실시간 추가 분석
            if search_ticker and search_ticker not in df['Ticker'].values:
                with st.spinner(f"{search_ticker} 데이터 분석 중..."):
                    new_row = analyze_single_ticker(search_ticker, y_start, h_start, today_end)
                    if new_row:
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        df = df.sort_values('종합점수', ascending=False)
                    else: st.error(f"{search_ticker} 데이터를 찾을 수 없습니다.")

            cols = ['Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)', 'Market Cap', 'Sales', 'Income', 'P/E', '3Y Avg P/E', 'Forward P/E', 'PEG', 'P/S', 'EPS next 5Y', 'Oper. Margin', 'EPS Q/Q', 'Sales Q/Q']
            existing_cols = [c for c in cols if c in df.columns]

            def highlight_row(row):
                if row.Ticker == search_ticker: return ['background-color: #1B2631; color: #F1C40F; font-weight: bold'] * len(row)
                return [''] * len(row)

            st.dataframe(df[existing_cols].style.apply(highlight_row, axis=1), hide_index=True, use_container_width=True, column_config={c: st.column_config.Column(alignment="right") for c in existing_cols})
        else: st.info("조건을 만족하는 종목이 없습니다.")
