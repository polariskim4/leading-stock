import pandas as pd
import yfinance as yf
import requests

# 1. 403 Forbidden 에러 방지를 위한 세션 설정
def get_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    return session

def get_recommendations(tickers):
    results = []
    session = get_session()
    
    for ticker in tickers:
        try:
            # session을 사용하여 데이터 로드 (403 에러 방지)
            stock = yf.Ticker(ticker, session=session)
            df = stock.history(period="60d")
            
            if df.empty or len(df) < 20:
                continue
            
            # SMA 20 계산
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            
            current_price = df['Close'].iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].mean()
            sma_20 = df['SMA_20'].iloc[-1]
            
            # 지표 산출
            sma_ratio = (current_price / sma_20) if sma_20 != 0 else 1
            vol_ratio = (current_vol / avg_vol) if avg_vol != 0 else 1
            
            results.append({
                'Ticker': ticker,
                'Price': round(current_price, 2),
                'SMA_20': round(sma_20, 2),
                'Volume': int(current_vol),
                'SMA_Ratio': sma_ratio,
                'Vol_Ratio': vol_ratio
            })
        except Exception as e:
            print(f"Error processing {ticker}: {e}")
            
    res_df = pd.DataFrame(results)
    
    if not res_df.empty:
        # 점수 정규화 (Min-Max Scaling)
        # 모든 종목이 1개일 경우를 대비해 분모가 0이 되는 것 방지
        def normalize(series):
            if series.max() <= series.min():
                return 100
            return (series - series.min()) / (series.max() - series.min()) * 100

        res_df['SMA_Score'] = normalize(res_df['SMA_Ratio'])
        res_df['Vol_Score'] = normalize(res_df['Vol_Ratio'])
        
        # 2. 종합 점수 계산 (SMA 70%, 거래량 30%)
        res_df['Total_Score'] = (res_df['SMA_Score'] * 0.7) + (res_df['Vol_Score'] * 0.3)
        res_df['Total_Score'] = res_df['Total_Score'].round(2)
        
        # 3. 10개로 확대 및 정렬
        res_df = res_df.sort_values(by='Total_Score', ascending=False).head(10)
        
        # 최종 출력 컬럼 정리
        final_display = res_df[['Ticker', 'Price', 'SMA_20', 'Volume', 'Total_Score']]
        return final_display.reset_index(drop=True)
    
    return res_df

# 실행 예시
# tickers = ["AAPL", "TSLA", "NVDA", "MSFT", "AMD", "GOOGL", "AMZN", "META", "NFLX", "INTC"]
# print(get_recommendations(tickers))
