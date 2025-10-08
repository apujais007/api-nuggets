  import os
  import requests
  import pandas as pd
  from datetime import datetime, timedelta

  excel_path = "data/grades_updates.xlsx"
  os.makedirs(os.path.dirname(excel_path), exist_ok=True)

  API_KEY = os.environ.get("FMP_API_KEY")
  BOT_TOKEN = os.environ.get("BOT_TOKEN")
  CHAT_ID = os.environ.get("CHAT_ID")

  def get_penny_stocks():
      """Fetch penny stocks strictly from NASDAQ/NYSE that exist on Yahoo Finance"""
      url = f"https://financialmodelingprep.com/api/v3/stock-screener?marketCapMoreThan=10000000&priceLowerThan=5&limit=1000&apikey={API_KEY}"
      r = requests.get(url)
      data = r.json()
      
      symbols = []
      for item in data:
          exchange = item.get('exchange', '')
          symbol = item.get('symbol', '')
          # Only NASDAQ or NYSE
          if exchange in ["NASDAQ", "NYSE"]:
              # Remove any foreign suffixes or invalid tickers
              if '.' not in symbol and '-' not in symbol:
                  symbols.append(symbol)
      return symbols

  def get_sp500_symbols():
      """Fetch all SP500 symbols"""
      url = f"https://financialmodelingprep.com/api/v3/sp500_constituent?apikey={API_KEY}"
      r = requests.get(url)
      data = r.json()
      return [item['symbol'] for item in data]

  def get_historical(symbol, limit=20, test_date=None):
      """Fetch last `limit` days historical prices with volume"""
      url = f"https://financialmodelingprep.com/stable/historical-price-eod/full?symbol={symbol}&apikey={API_KEY}"
      r = requests.get(url)
      if r.status_code != 200:
          print(f"Error fetching {symbol}: status code {r.status_code}")
          return None
      try:
          data = r.json()
      except Exception as e:
          print(f"Error decoding JSON for {symbol}: {e}")
          return None
      if not data:
          return None

      df = pd.DataFrame(data[:limit])
      if df.empty:
          return None

      df['date'] = pd.to_datetime(df['date'])
      df = df[::-1]  # oldest → newest

      if test_date:
          test_dt = pd.to_datetime(test_date)
          df = df[df['date'] <= test_dt]

      return df

  def score_stock(df):
      """Compute score based on breakout and volume criteria and return breakdown"""
      if df is None or len(df) < 10:
          return 0, "", [], []

      df['ma5'] = df['close'].rolling(5).mean()
      df['ma10'] = df['close'].rolling(10).mean()
      df['pct_change'] = df['close'].pct_change() * 100
      score = 0
      breakdown = []

      # 1️⃣ Price above MA5 and MA10
      if df['close'].iloc[-1] > df['ma5'].iloc[-1] and df['close'].iloc[-1] > df['ma10'].iloc[-1]:
          score += 1
          breakdown.append("Price above MA5 & MA10")

      # 2️⃣ Recent price surge (>5%)
      if df['pct_change'].iloc[-1] > 5:
          score += 1
          breakdown.append("Recent price surge >5%")

      # 3️⃣ Previous day price surge (>3%)
      if df['pct_change'].iloc[-2] > 3:
          score += 1
          breakdown.append("Previous day surge >3%")

      # 4️⃣ Near 20-day high breakout
      high_20 = df['close'].rolling(20).max().iloc[-1]
      if df['close'].iloc[-1] >= 0.95 * high_20:
          score += 1
          breakdown.append("Near 20-day high breakout")

      # 5️⃣ Volume surge
      last_5_volume = []
      if 'volume' in df.columns:
          df['vol_ma5'] = df['volume'].rolling(5).mean()
          last_5_volume = df['volume'].iloc[-5:].tolist()
          if df['volume'].iloc[-1] > 1.5 * df['vol_ma5'].iloc[-1]:
              score += 1
              breakdown.append("Volume surge >1.5 * 5-day avg")

      # Last 5 closes and volumes
      last_5 = df.iloc[-5:]
      last_5_close = [f"{d.strftime('%Y-%m-%d')}: {c}" for d, c in zip(last_5['date'], last_5['close'])]
      last_5_volume = [f"{d.strftime('%Y-%m-%d')}: {int(v):,}" for d, v in zip(last_5['date'], last_5['volume'])]

      return score, "; ".join(breakdown), last_5_close, last_5_volume

  def pick_stocks(test_date=None):
      symbols = get_penny_stocks()
      results = []

      for sym in symbols:
          df = get_historical(sym, test_date=test_date)
          sc, breakdown, last_5_close, last_5_volume = score_stock(df)
          if sc > 1:  # only strong candidates
              results.append({
                  "symbol": sym,
                  "score": sc,
                  "breakdown": breakdown,
                  "last_5_close": last_5_close,
                  "last_5_volume": last_5_volume
              })

      if not results:
          print("No stocks matching criteria on test date.")
          return []

      results.sort(key=lambda x: x['score'], reverse=True)
      return results[:TOP_N]

def score_stock_down(df):
    """Compute score for downward breakout stocks"""
    if df is None or len(df) < 10:
        return 0, "", [], []

    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['pct_change'] = df['close'].pct_change() * 100
    score = 0
    breakdown = []

    # 1️⃣ Price below MA5 and MA10
    if df['close'].iloc[-1] < df['ma5'].iloc[-1] and df['close'].iloc[-1] < df['ma10'].iloc[-1]:
        score += 1
        breakdown.append("Price below MA5 & MA10")

    # 2️⃣ Recent price drop (>5%)
    if df['pct_change'].iloc[-1] < -5:
        score += 1
        breakdown.append("Recent price drop >5%")

    # 3️⃣ Previous day drop (>3%)
    if df['pct_change'].iloc[-2] < -3:
        score += 1
        breakdown.append("Previous day drop >3%")

    # 4️⃣ Near 20-day low breakout
    low_20 = df['close'].rolling(20).min().iloc[-1]
    if df['close'].iloc[-1] <= 1.05 * low_20:  # within 5% of 20-day low
        score += 1
        breakdown.append("Near 20-day low breakout")

    # 5️⃣ Volume surge (optional)
    last_5_volume = []
    if 'volume' in df.columns:
        df['vol_ma5'] = df['volume'].rolling(5).mean()
        last_5_volume = df['volume'].iloc[-5:].tolist()
        if df['volume'].iloc[-1] > 1.5 * df['vol_ma5'].iloc[-1]:
            score += 1
            breakdown.append("Volume surge >1.5 * 5-day avg")

    # Last 5 closes and volumes
    last_5 = df.iloc[-5:]
    last_5_close = [f"{d.strftime('%Y-%m-%d')}: {c}" for d, c in zip(last_5['date'], last_5['close'])]
    last_5_volume = [f"{d.strftime('%Y-%m-%d')}: {int(v):,}" for d, v in zip(last_5['date'], last_5['volume'])]

    return score, "; ".join(breakdown), last_5_close, last_5_volume


# --- Function to pick downward S&P500 stocks ---
def pick_sp500_stocks_down(test_date=None):
    sp500_symbols = get_sp500_symbols()
    results = []
    for sym in sp500_symbols:
        df = get_historical(sym, test_date=test_date)
        sc, breakdown, last_5_close, last_5_volume = score_stock_down(df)
        if sc > 1:  # strong candidates
            results.append({
                "symbol": sym,
                "score": sc,
                "breakdown": breakdown,
                "last_5_close": last_5_close,
                "last_5_volume": last_5_volume
            })
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:TOP_N]

def pick_sp500_stocks_up(test_date=None):
        results = []
        for sym in sp500_symbols:
            df = get_historical(sym, test_date=test_date)
            sc, breakdown, last_5_close, last_5_volume = score_stock(df)
            if sc > 1:
                results.append({
                    "symbol": sym,
                    "score": sc,
                    "breakdown": breakdown,
                    "last_5_close": last_5_close,
                    "last_5_volume": last_5_volume
                })
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:TOP_N]

def pick_sp500_stocks_down(test_date=None):
    sp500_symbols = get_sp500_symbols()
    results = []
    for sym in sp500_symbols:
        df = get_historical(sym, test_date=test_date)
        sc, breakdown, last_5_close, last_5_volume = score_stock_down(df)
        if sc > 1:  # strong candidates
            results.append({
                "symbol": sym,
                "score": sc,
                "breakdown": breakdown,
                "last_5_close": last_5_close,
                "last_5_volume": last_5_volume
            })
    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:TOP_N]        

def append_df_to_excel(df, sheet_name, excel_path):
    """
    Append a DataFrame to a sheet in an Excel file.
    If the sheet/file doesn't exist, it creates them.
    """
    if os.path.exists(excel_path):
        # Read existing sheet if it exists
        try:
            existing_df = pd.read_excel(excel_path, sheet_name=sheet_name, engine="openpyxl")
            df_combined = pd.concat([existing_df, df], ignore_index=True)
            df_combined.drop_duplicates(inplace=True)
        except ValueError:
            # Sheet doesn't exist yet
            df_combined = df
    else:
        df_combined = df

    # Write back to Excel
    with pd.ExcelWriter(excel_path, engine="openpyxl", mode="a" if os.path.exists(excel_path) else "w") as writer:
        df_combined.to_excel(writer, sheet_name=sheet_name, index=False)
      
if __name__ == "__main__":
    #test_date = "2025-09-28"  # Change for backtesting
    test_date = None
    # Top Penny Stocks
    penny_symbols = get_penny_stocks()
    top_penny = pick_stocks(test_date=test_date)  # <-- use pick_stocks which handles symbol iteration
    if top_penny:
        df_penny = pd.DataFrame(top_penny)
        print(f"Top Penny Stock Picks as of {test_date}:")
        pd.set_option('display.max_colwidth', None)
        print(df_penny)

    # Top SP500 Stocks
    sp500_symbols = get_sp500_symbols()
    top_sp500 = pick_sp500_stocks_up(test_date=test_date)
    if top_sp500:
        df_sp500 = pd.DataFrame(top_sp500)
        print(f"\nTop S&P500 Stock Picks as of {test_date}:")
        pd.set_option('display.max_colwidth', None)
        print(df_sp500) 


    bottom_sp500 = pick_sp500_stocks_down(test_date=test_date)
    if bottom_sp500:
        df_sp500_down = pd.DataFrame(bottom_sp500)
        print(f"\nBottom S&P500 Stock Picks (Downward) as of {test_date}:")
        pd.set_option('display.max_colwidth', None)
        print(df_sp500_down)    

    if not df_penny.empty:
      append_df_to_excel(df_penny, "Top Penny Stocks", excel_path)
    if not df_sp500.empty:
      append_df_to_excel(df_sp500, "Top SP500 Stocks", excel_path)
    if not df_sp500_down.empty:
      append_df_to_excel(df_sp500_down, "Bottom SP500 Stocks", excel_path)
    print(f"All stock pick data appended to Excel: {excel_path}")
