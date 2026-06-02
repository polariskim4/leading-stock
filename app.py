import pandas as pd
import yfinance as yf
import requests

def get_recommendations(tickers):
    results = []
    
    # 1. 403 에러 방지를 위한 헤더 설정
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    print(f"데이터 분석 시작 (총 {len(tickers)} 종목)...")

    for ticker in tickers:
        try:
            # yfinance의 download 기능을 사용하여 한 번에 데이터를 가져옵니다.
            # 최근 60일치 데이터를 가져오며, 에러 발생 시 로그를 남깁니다.
            df = yf.download(ticker, period="60d", interval="1d", progress=False, timeout=10)
            
            if df.empty or len(df) < 20:
                # 데이터가 없거나 SMA_20을 계산하기에 데이터가 부족한 경우
                continue
            
            # SMA 20 계산
            df['SMA_20'] = df['Close'].rolling(window=20).mean()
            
            # 최근 데이터 추출
            current_price = float(df['Close'].iloc[-1])
            current_vol = float(df['Volume'].iloc[-1])
            avg_vol = float(df['Volume'].mean())
            sma_20 = float(df['SMA_20'].iloc[-1])
            
            if pd.isna(sma_20): continue # SMA 값이 NaN이면 스킵

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
            print(f"✅ {ticker} 분석 완료")
            
        except Exception as e:
            print(f"❌ {ticker} 분석 중 오류 발생: {e}")
            
    if not results:
        print("분석 결과가 없습니다. 티커 심볼이나 네트워크 상태를 확인해주세요.")
        return pd.DataFrame()
    
    res_df = pd.DataFrame(results)
    
    # 점수 정규화 (Min-Max Scaling)
    def normalize(series):
        if series.max() == series.min():
            return 100.0
        return (series - series.min()) / (series.max() - series.min()) * 100

    # SMA 70%, 거래량 30% 가중치 적용
    res_df['SMA_Score'] = normalize(res_df['SMA_Ratio'])
    res_df['Vol_Score'] = normalize(res_df['Vol_Ratio'])
    res_df['Total_Score'] = (res_df['SMA_Score'] * 0.7) + (res_df['Vol_Score'] * 0.3)
    
    # 10개 종목 선별 및 정렬
    final_df = res_df.sort_values(by='Total_Score', ascending=False).head(10)
    
    # 출력 컬럼 정리
    final_display = final_df[['Ticker', 'Price', 'SMA_20', 'Volume', 'Total_Score']].copy()
    final_display['Total_Score'] = final_display['Total_Score'].round(2)
    
    return final_display.reset_index(drop=True)

# 테스트 실행 (미국 주식 예시)
# 만약 한국 주식을 하신다면 "005930.KS" 처럼 뒤에 .KS나 .KQ를 붙여야 합니다.
target_tickers = ["AAPL", "TSLA", "NVDA", "MSFT", "AMD", "GOOGL", "AMZN", "META", "NFLX", "INTC"]
recommendations = get_recommendations(target_tickers)

if not recommendations.empty:
    print("\n[최종 추천 종목 상위 10개]")
    print(recommendations)
