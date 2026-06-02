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
    if val is None or val == '-' or val == "":
        return "-"
    suffix = ""
    num_str = str(val).replace(',', '').replace('$', '')
    
    if num_str.endswith('%'):
        suffix = '%'
        num_str = num_str[:-1]
    elif len(num_str) > 1 and num_str[-1].upper() in ['T', 'B', 'M', 'K']:
        suffix = num_str[-1].upper()
        num_str = num_str[:-1]
    
    try:
        return f"{float(num_str):.1f}{suffix}"
    except ValueError:
        return val

def parse_market_cap(cap_str):
    """문자열 시총을 숫자로 변환 (3y PE 계산용)"""
    if cap_str == '-': return 0
    multiplier = 1
    clean_str = cap_str.replace(',', '').replace('$', '')
    if 'T' in clean_str: multiplier = 1e12
    elif 'B' in clean_str: multiplier = 1e9
    elif 'M' in clean_str: multiplier = 1e6
    try:
        return float(''.join(c for c in clean_str if c.isdigit() or c == '.')) * multiplier
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

# 4. 데이터 로드 함수
@st.cache_data(ttl=86400)
def get_ticker_source(market_type):
    headers = {'User-Agent': 'Mozilla/5.0'}
    if market_type == "Nasdaq100":
        url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
        df = pd.read_html(io.StringIO(requests.get(url, headers=headers).text), match='Ticker')[0]
        ticker_col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
        return df[ticker_col].astype(str).str.replace('.', '-', regex=False).tolist()
    else:
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        return pd.read_html(io.StringIO(requests.get(url, headers=headers).text), match='Symbol')[0]

# 5. 메인 UI
sp500_raw = get_ticker_source("SP500")
sectors = sorted(sp500_raw['GICS Sector'].unique().tolist())
selected_menu = st.sidebar.selectbox("분석 대상 선택", sectors + ["Nasdaq100"])

target_tickers = get_ticker_source("Nasdaq100") if selected_menu == "Nasdaq100" else sp500_raw[sp500_raw['GICS Sector'] == selected_menu]['Symbol'].tolist()

if st.sidebar.button("분석 시작"):
    candidates = []
    perf_results = []
    today = datetime.now()
    y_start, h_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d'), (today - timedelta(weeks=160)).strftime('%Y-%m-%d')

    with st.status("종목 분석 중...", expanded=True) as status:
        for i in range(0, len(target_tickers), 15):
            chunk = target_tickers[i:i + 15]
            try:
                ytd_all = yf.download(chunk, start=y_start, end=datetime(today.year, 1, 2).strftime('%Y-%m-%d'), interval="1d", group_by='ticker', progress=False)
                w_all = yf.download(chunk, start=h_start, interval="1wk", group_by='ticker', progress=False)
                
                for ticker in chunk:
                    try:
                        w_df = w_all[ticker].dropna()
                        if len(w_df) < 100: continue
                        curr_p = w_df['Close'].iloc[-1]
                        
                        # YTD 계산
                        base_p = ytd_all[ticker]['Close'].iloc[-1] if ticker in ytd_all.columns.levels[0] and not ytd_all[ticker].empty else w_df['Close'].iloc[0]
                        ytd_ret = ((curr_p / base_p) - 1) * 100
                        perf_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})

                        # 기술적 필터
                        ma50, ma100 = w_df['Close'].rolling(50).mean().iloc[-1], w_df['Close'].rolling(100).mean().iloc[-1]
                        max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                        vol_ratio = (w_df['Volume'].iloc[-1] / max_v_8w) if max_v_8w > 0 else 1.0

                        if ma50 > ma100 and vol_ratio <= 0.65:
                            ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                            dist20, dist50 = abs(curr_p - ma20)/ma20 * 100, abs(curr_p - ma50)/ma50 * 100
                            min_dist = min(dist20, dist50)
                            
                            candidates.append({
                                'Ticker': ticker, '종합점수': max(0, (1 - min_dist/10)*60 + (1 - vol_ratio)*40),
                                '현재가': curr_p, 'YTD': ytd_ret,
                                '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                '인접SMA': 'SMA 20' if dist20 < dist50 else 'SMA 50',
                                '인접도': min_dist, '거래량비중(%)': vol_ratio * 100
                            })
                    except: continue
            except: pass
        
        # 상위 10개 펀더멘털 분석 (3Y PE 포함)
        final_recs = []
        if candidates:
            top_10 = pd.DataFrame(candidates).sort_values('종합점수', ascending=False).head(10)
            for _, row in top_10.iterrows():
                f_data = get_finviz_fundamentals(row['Ticker'])
                if f_data:
                    avg_pe = "-"
                    try:
                        t_obj = yf.Ticker(row['Ticker'])
                        income = t_obj.income_stmt
                        # 'Net Income' 행을 찾아 최근 3개년 평균 계산
                        if not income.empty:
                            # 다양한 인덱스 명칭 대응 (Net Income 또는 NetIncome)
                            ni_row = income.loc[income.index.str.contains('Net Income', case=False)]
                            if not ni_row.empty:
                                avg_ni = ni_row.iloc[0].head(3).mean()
                                m_cap_val = parse_market_cap(f_data['Market Cap'])
                                if avg_ni > 0:
                                    avg_pe = m_cap_val / avg_ni
                    except: pass
                    
                    row_dict = row.to_dict()
                    row_dict.update(f_data)
                    row_dict['3Y Avg P/E'] = format_to_one_decimal(avg_pe)
                    # 기존 퍼센트 지표 포맷팅
                    row_dict['YTD'] = f"{row_dict['YTD']:.1f}%"
                    row_dict['1Y_고점대비'] = f"{row_dict['1Y_고점대비']:.1f}%"
                    row_dict['거래량비중(%)'] = f"{row_dict['거래량비중(%)']:.1f}%"
                    final_recs.append(row_dict)
                time.sleep(0.2)
        status.update(label="분석 완료!", state="complete")

    # 결과 출력
    if perf_results:
        st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
        perf_df = pd.DataFrame(perf_results).sort_values('YTD', ascending=False).head(3)
        # hide_index=True를 사용하여 왼쪽의 불필요한 인덱스 번호를 제거
        st.dataframe(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}), hide_index=True, use_container_width=True)

        st.divider()
        st.subheader("🎯 기술적 눌림목 추천 TOP 10 (종합 점수순)")
        if final_recs:
            df = pd.DataFrame(final_recs)
            cols = ['Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)', 'Market Cap', 'Sales', 'Income', 'P/E', '3Y Avg P/E', 'Forward P/E', 'PEG']
            # 여기서도 hide_index=True 적용
            st.dataframe(df[cols], hide_index=True, use_container_width=True, column_config={c: st.column_config.Column(alignment="right") for c in cols})
        else:
            st.info("조건을 만족하는 눌림목 종목이 없습니다.")
