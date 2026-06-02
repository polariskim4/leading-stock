import streamlit as st
import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
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

st.title("📈 섹터 주도주 분석 및 Finviz 기반 눌림목 추천")

# 2. 유틸리티 함수: Finviz 데이터 포맷팅 및 파싱
def format_to_one_decimal(val):
    """Finviz의 문자열 데이터를 소수점 한자리로 포맷팅"""
    if not val or val == '-':
        return "-"
    suffix = ""
    num_str = val.replace(',', '')
    
    if num_str.endswith('%'):
        suffix = '%'
        num_str = num_str[:-1]
    elif num_str[-1].upper() in ['T', 'B', 'M', 'K'] and len(num_str) > 1:
        suffix = num_str[-1].upper()
        num_str = num_str[:-1]
    
    try:
        return f"{float(num_str):.1f}{suffix}"
    except ValueError:
        return val

# 3. Finviz 스크래핑 함수 (핵심: yfinance의 None 문제 해결)
def get_finviz_fundamentals(ticker):
    url = f"https://finviz.com/quote.ashx?t={ticker.upper()}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', class_='snapshot-table2')
        if not table:
            return None
        
        cells = table.find_all('td')
        temp_dict = {}
        for i in range(0, len(cells), 2):
            label = cells[i].text.strip()
            value = cells[i+1].text.strip()
            temp_dict[label] = value
            
        # 요청하신 지표 매핑
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
    except Exception:
        return None

# 4. 날짜 설정
today = datetime.now()
last_year_start_range = datetime(today.year - 1, 12, 20).strftime('%Y-%m-%d')
last_year_end_range = datetime(today.year, 1, 2).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')
hist_start = (today - timedelta(weeks=160)).strftime('%Y-%m-%d')

# 5. 티커 리스트 가져오기
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

# 6. 메인 로직
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
        candidates = []
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})

        with st.status(f"{selected_menu} 기술적 분석 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            chunk_size = 20

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
                            
                            # YTD 수익률 계산
                            if ticker in ytd_base_all.columns.levels[0]:
                                t_base = ytd_base_all[ticker].dropna()
                                base_p = t_base['Close'].iloc[-1] if not t_base.empty else w_df['Close'].iloc[0]
                            else: base_p = w_df['Close'].iloc[0]
                                
                            curr_p = w_df['Close'].iloc[-1]
                            ytd_ret = ((curr_p / base_p) - 1) * 100
                            performance_results.append({'Ticker': ticker, '현재가': curr_p, 'YTD': ytd_ret})

                            # 눌림목 필터: 정배열 & 거래량 감소
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

                                candidates.append({
                                    'Ticker': ticker, 'YTD': ytd_ret, '현재가': curr_p,
                                    '1Y_고점대비': ((curr_p / w_df['Close'].tail(52).max()) - 1) * 100,
                                    '거래량비중(%)': vol_ratio * 100,
                                    '인접SMA': 'SMA 20' if dist_ma20 < dist_ma50 else 'SMA 50',
                                    '인접도': min_dist, '종합점수': max(0, score)
                                })
                        except: continue
                except: pass
                progress_bar.progress(min((i + chunk_size) / len(target_tickers), 1.0))

            # --- 재무 데이터 스크래핑 (상위 10개만) ---
            final_recs = []
            if candidates:
                status.update(label="Finviz 재무 데이터 수집 중...", state="running")
                top_candidates = pd.DataFrame(candidates).sort_values('종합점수', ascending=False).head(10)
                
                for _, row in top_candidates.iterrows():
                    ticker = row['Ticker']
                    fundamentals = get_finviz_fundamentals(ticker)
                    if fundamentals:
                        row_data = row.to_dict()
                        row_data.update(fundamentals)
                        final_recs.append(row_data)
                    time.sleep(0.2) # Finviz 차단 방지

            status.update(label="분석 완료!", state="complete")

        # 7. 결과 출력
        if performance_results:
            st.subheader(f"🏆 {selected_menu} 성과 상위 TOP 3 (YTD)")
            perf_df = pd.DataFrame(performance_results).sort_values('YTD', ascending=False).head(3)
            st.dataframe(perf_df.style.format({'현재가': '{:.1f}', 'YTD': '{:.1f}%'}), hide_index=True, use_container_width=True)

            st.divider()
            st.subheader("🎯 기술적 눌림목 추천 TOP 10 (Finviz 재무 지표 포함)")
            if final_recs:
                recs_df = pd.DataFrame(final_recs)
                # 요청하신 순서대로 컬럼 재정렬
                display_cols = [
                    'Ticker', '종합점수', '현재가', 'YTD', '1Y_고점대비', '인접SMA', '인접도', '거래량비중(%)',
                    'Market Cap', 'Sales', 'Income', 'P/E', 'Forward P/E', 'PEG', 'P/S', 
                    'EPS next 5Y', 'Oper. Margin', 'EPS Q/Q', 'Sales Q/Q'
                ]
                # 컬럼이 존재할 때만 출력
                existing_cols = [c for c in display_cols if c in recs_df.columns]
                
                # 수치 데이터 포맷팅 및 오른쪽 정렬
                st.dataframe(
                    recs_df[existing_cols].style.format({
                        '종합점수': '{:.1f}', '현재가': '{:.1f}', 'YTD': '{:.1f}%', 
                        '1Y_고점대비': '{:.1f}%', '인접도': '{:.1f}', '거래량비중(%)': '{:.1f}%'
                    }, na_rep='-'),
                    hide_index=True, 
                    use_container_width=True
                )
            else:
                st.info("조건을 만족하는 눌림목 종목이 없습니다.")
        else:
            st.error("데이터 수집에 실패했습니다.")
