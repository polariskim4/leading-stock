import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
import io
import time
from datetime import datetime, timedelta

# 1. 페이지 설정 및 UI 스타일 (오른쪽 정렬 강제 로직)
st.set_page_config(page_title="Market Alpha Hunter", layout="wide")

# CSS를 통한 전역 오른쪽 정렬 설정
st.markdown("""
    <style>
    .main { font-size: 0.85rem; }
    /* 테이블 헤더 및 셀 텍스트 오른쪽 정렬 */
    thead tr th { text-align: right !important; }
    div[data-testid="stDataFrame"] td { text-align: right !important; }
    div[data-testid="stDataFrame"] th { text-align: right !important; }
    /* 숫자 데이터 외의 텍스트 컬럼도 오른쪽 정렬되도록 강제 */
    [data-testid="stTable"] { text-align: right !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📈 섹터 주도주 분석 및 Finviz 기반 눌림목 추천")

# 2. 유틸리티 함수: 소수점 한자리 및 정렬용 포맷팅
def format_to_one_decimal(val):
    if not val or val == '-':
        return "-"
    suffix = ""
    num_str = val.replace(',', '').replace('$', '')
    
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

# 3. Finviz 스크래핑 함수 (재무 정보 보증)
def get_finviz_fundamentals(ticker):
    url = f"https://finviz.com/quote.ashx?t={ticker.upper()}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200: return None
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', class_='snapshot-table2')
        if not table: return None
        
        cells = table.find_all('td')
        temp_dict = {}
        for i in range(0, len(cells), 2):
            label = cells[i].text.strip()
            value = cells[i+1].text.strip()
            temp_dict[label] = value
            
        metrics = {
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
        return metrics
    except: return None

# 4. 티커 소스 로직
@st.cache_data(ttl=86400)
def get_tickers(market_type):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        if market_type == "Nasdaq100":
            url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
            df = pd.read_html(io.StringIO(requests.get(url, headers=headers).text), match='Ticker')[0]
            ticker_col = 'Ticker' if 'Ticker' in df.columns else df.columns[1]
            return df[ticker_col].astype(str).str.replace('.', '-', regex=False).tolist()
        else: # S&P 500 Sectors
            url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
            df = pd.read_html(io.StringIO(requests.get(url, headers=headers).text), match='Symbol')[0]
            df['Symbol'] = df['Symbol'].str.replace('.', '-', regex=False)
            return df

    except: return pd.DataFrame()

# 5. 메인 UI 및 분석
sp500_raw = get_tickers("SP500")
if not sp500_raw.empty:
    sectors = sorted(sp500_raw['GICS Sector'].unique().tolist())
    selected_menu = st.sidebar.selectbox("분석 대상 선택", sectors + ["Nasdaq100"])
    
    if selected_menu == "Nasdaq100":
        target_tickers = get_tickers("Nasdaq100")
    else:
        target_tickers = sp500_raw[sp500_raw['GICS Sector'] == selected_menu]['Symbol'].tolist()
    
    st.sidebar.write(f"조회 대상: {len(target_tickers)}개 종목")
    if st.sidebar.button("분석 시작"):
        perf_results = []
        candidates = []
        
        # 날짜 설정
        today = datetime.now()
        y_start = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
        y_end = datetime(today.year, 1, 2).strftime('%Y-%m-%d')
        h_start = (today - timedelta(weeks=160)).strftime('%Y-%m-%d')

        with st.status("데이터 분석 및 지표 계산 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            for i in range(0, len(target_tickers), 15):
                chunk = target_tickers[i:i + 15]
                try:
                    ytd_all = yf.download(chunk, start=y_start, end=y_end, interval="1d", group_by='ticker', progress=False)
                    w_all = yf.download(chunk, start=h_start, interval="1wk", group_by='ticker', progress=False)
                    
                    for ticker in chunk:
                        try:
                            if ticker not in w_all.columns.levels[0]: continue
                            w_df = w_all[ticker].dropna()
                            if len(w_df) < 100: continue
                            
                            # YTD 및 기술적 분석
                            base_p = ytd_all[ticker]['Close'].iloc[-1] if ticker in ytd_all.columns.levels[0] and not ytd_all[ticker].empty else w_df['Close'].iloc[0]
                            curr_p = w_df['Close'].iloc[-1]
                            ytd_ret = ((curr_p / base_p) - 1) * 100
                            perf_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})

                            ma50, ma100 = w_df['Close'].rolling(50).mean().iloc[-1], w_df['Close'].rolling(100).mean().iloc[-1]
                            max_v_8w = w_df['Volume'].iloc[-8:-1].max()
                            vol_ratio = (w_df['Volume'].iloc[-1] / max_v_8w) if max_v_8w > 0 else 1.0

                            if ma50 > ma100 and vol_ratio <= 0.65:
                                ma20 = w_df['Close'].rolling(20).mean().iloc[-1]
                                min_dist = min(abs(curr_p - ma20)/ma20, abs(curr_p - ma50)/ma50) * 100
                                candidates.append({
                                    'Ticker': ticker, '종합점수': max(0, ((1 - min_dist/10)*60 + (1 - vol_ratio)*40)),
                                    '현재가': curr_p, 'YTD': ytd_ret,
                                    '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                    '인접SMA': 'SMA 20' if abs(curr_p - ma20)/ma20 < abs(curr_p - ma50)/ma50 else 'SMA 50',
                                    '인접도': min_dist, '거래량비중(%)': vol_ratio * 100
                                })
                        except: continue
                except: pass
                progress_bar.progress(min((i + 15) / len(target_tickers), 1.0))

            # --- 상위 10개 Finviz 스크래핑 ---
            final_recs = []
            if candidates:
                status.update(label="Finviz 재무 데이터 수집 중...", state="running")
                top_10 = pd.DataFrame(candidates).sort_values('종합점수', ascending=False).head(10)
                for _, row in top_10.iterrows():
                    f_data = get_finviz_fundamentals(row['Ticker'])
                    if f_data:
                        r_dict = row.to_dict()
                        r_dict.update(f_data)
                        # 기술적 지표들도 소수점 포맷팅
                        r_dict['종합점수'] = format_to_one_decimal(str(r_dict['종합점수']))
                        r_dict['현재가'] = format_to_one_decimal(str(r_dict['현재가']))
                        r_dict['YTD'] = format_to_one_decimal(str(r_dict['YTD'])) + "%"
                        r_dict['1Y_고점대비'] = format_to_one_decimal(str(r_dict['1Y_고점대비'])) + "%"
                        r_dict['인접도'] = format_to_one_decimal(str(r_dict['인접도']))
                        r_dict['거래량비중(%)'] = format_to_one_decimal(str(r_dict['거래량비중(%)'])) + "%"
                        final_recs.append(r_dict)
                    time.sleep(0.2)
            status.update(label="분석 완료!", state="complete")

        # 6. 결과 출력 (전부 오른쪽 정렬)
        if perf_results:
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(perf_results).sort_values('YTD', ascending=False).head(3)
            # 메트릭 형태로 간단히 표시하거나 테이블로 표시
            st.table(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}))

            st.divider()
            st.subheader("🎯 기술적 눌림목 추천 TOP 10 (Finviz Fundamentals)")
            if final_recs:
                df_final = pd.DataFrame(final_recs)
                display_cols = [
                    'Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)',
                    'Market Cap', 'Sales', 'Income', 'P/E', 'Forward P/E', 'PEG', 'P/S', 
                    'EPS next 5Y', 'Oper. Margin', 'EPS Q/Q', 'Sales Q/Q'
                ]
                # DataFrame에 없는 컬럼 제외 후 정렬
                actual_cols = [c for c in display_cols if c in df_final.columns]
                
                # 모든 컬럼에 대해 오른쪽 정렬 설정
                col_config = {col: st.column_config.Column(alignment="right") for col in actual_cols}

                st.dataframe(
                    df_final[actual_cols],
                    hide_index=True,
                    use_container_width=True,
                    column_config=col_config
                )
            else:
                st.info("조건을 만족하는 눌림목 종목이 없습니다.")
