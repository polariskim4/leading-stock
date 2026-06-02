import pandas as pd
import yfinance as yf
import requests

# 403 Forbidden 에러를 방지하기 위한 세션 설정
def get_safe_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'
    })
    return session

def get_recommendations(tickers):
    results = []
    session = get_safe_session()
    
    print(f"데이터 분석을 시작합니다. 대상 종목: {len(tickers)}개")
    
    for ticker in tickers:
        try:
            # 기존 로직 유지: 데이터 로드
            # session을 추가하여 403 에러를 방지합니다.
            stock = yf.Ticker(ticker, session=session)
            df = stock.history(period="60d")
            
            if df.empty or len(df) < 20:
                continue
            
            # SMA 20 계산 (기존 기준)
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            
            current_price = df['Close'].iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].mean()
            sma_20 = df['SMA_20'].iloc[-1]
            
            if pd.isna(sma_20): continue

            # 지표 산출 (점수화의 기반)
            sma_ratio = current_price / sma_20  # SMA 대비 가격 위치
            vol_ratio = current_vol / avg_vol    # 평균 거래량 대비 현재 거래량
            
            results.append({
                'Ticker': ticker,
                'Price': round(current_price, 2),
                'SMA_20': round(sma_20, 2),
                'Volume': int(current_vol),
                'SMA_Ratio': sma_ratio,
                'Vol_Ratio': vol_ratio
            })
        except Exception as e:
            print(f"{ticker} 분석 중 건너뜀: {e}")
            
    res_df = pd.DataFrame(results)
    
    if not res_df.empty:
        # 가중치 계산을 위한 정규화 (0~100점 스케일링)
        def scale_score(series):
            if series.max() == series.min(): return 100
            return (series - series.min()) / (series.max() - series.min()) * 100

        res_df['SMA_Score'] = scale_score(res_df['SMA_Ratio'])
        res_df['Vol_Score'] = scale_score(res_df['Vol_Ratio'])
        
        # 1. 종합 점수 계산 (SMA 70%, 거래량 30%)
        res_df['Total_Score'] = (res_df['SMA_Score'] * 0.7) + (res_df['Vol_Score'] * 0.3)
        res_df['Total_Score'] = res_df['Total_Score'].round(2)
        
        # 2. 추천 종목 10개로 확대 및 정렬
        final_df = res_df.sort_values(by='Total_Score', ascending=False).head(10)
        
        # 출력 컬럼 정리 (요청대로 맨 오른쪽에 종합점수 표시)
        final_display = final_df[['Ticker', 'Price', 'SMA_20', 'Volume', 'Total_Score']]
        return final_display.reset_index(drop=True)
    
    else:
        print("조건에 맞는 데이터가 없습니다.")
        return pd.DataFrame()

# 사용 예시
# tickers = ["AAPL", "TSLA", "NVDA", "MSFT", "AMD", "GOOGL", "AMZN", "META", "NFLX", "INTC"]
# print(get_recommendations(tickers))
