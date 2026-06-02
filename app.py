import pandas as pd
import yfinance as yf

def get_recommendations(tickers):
    results = []
    
    # 1. 데이터 수집 및 기본 지표 계산 (어제와 동일한 방식)
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="60d", interval="1d", progress=False)
            if df.empty or len(df) < 20:
                continue
            
            # SMA 20일선 계산
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            
            current_price = df['Close'].iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            avg_vol = df['Volume'].mean()
            sma_20 = df['SMA_20'].iloc[-1]
            
            # 지표 산출
            sma_ratio = current_price / sma_20
            vol_ratio = current_vol / avg_vol
            
            results.append({
                'Ticker': ticker,
                'Price': round(current_price, 2),
                'SMA_20': round(sma_20, 2),
                'Volume': int(current_vol),
                'SMA_Ratio': sma_ratio,
                'Vol_Ratio': vol_ratio
            })
        except Exception:
            continue
            
    res_df = pd.DataFrame(results)
    
    if not res_df.empty:
        # 2. 종합 점수 계산 (SMA 70%, 거래량 30%)
        # 각 지표를 0~100점 사이로 환산하여 가중치 적용
        res_df['SMA_Score'] = (res_df['SMA_Ratio'] - res_df['SMA_Ratio'].min()) / (res_df['SMA_Ratio'].max() - res_df['SMA_Ratio'].min()) * 100
        res_df['Vol_Score'] = (res_df['Vol_Ratio'] - res_df['Vol_Ratio'].min()) / (res_df['Vol_Ratio'].max() - res_df['Vol_Ratio'].min()) * 100
        
        res_df['Total_Score'] = (res_df['SMA_Score'] * 0.7) + (res_df['Vol_Score'] * 0.3)
        res_df['Total_Score'] = res_df['Total_Score'].round(2)
        
        # 3. 10개로 확대 및 정렬
        final_df = res_df.sort_values(by='Total_Score', ascending=False).head(10)
        
        # 최종 결과 출력 (맨 오른쪽에 종합점수 표시)
        return final_df[['Ticker', 'Price', 'SMA_20', 'Volume', 'Total_Score']].reset_index(drop=True)
    
    return res_df

# 실행 예시
# tickers = ["AAPL", "TSLA", "NVDA", "MSFT", "AMD", "GOOGL", "AMZN", "META", "NFLX", "INTC"]
# print(get_recommendations(tickers))
