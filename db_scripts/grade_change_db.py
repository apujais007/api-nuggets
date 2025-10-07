import os
import sys
import requests
import pandas as pd
from datetime import datetime, timedelta, date
import sqlite3

csv_path = "data/grades_updates.csv"
os.makedirs(os.path.dirname(csv_path), exist_ok=True)

API_KEY = os.environ.get("FMP_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# def append_df_to_csv(df, file_path=csv_path):
#     if df.empty:
#         return 0

#     if not os.path.isfile(file_path):
#         df.to_csv(file_path, mode="w", header=True, index=False)
#     else:
#         df.to_csv(file_path, mode="a", header=False, index=False)

#     return len(df)
    
def get_json(url, params=None):
    if params is None:
        params = {}
    params['apikey'] = API_KEY
    r = requests.get(url, params=params)
    if r.status_code == 200:
        return r.json()
    else:
        print(f"Error {r.status_code} for URL {url}")
        return None

def fetch_sp500_symbols(top_n=100):
    url = "https://financialmodelingprep.com/api/v3/sp500_constituent"
    data = get_json(url)
    if not data:
        return []
    return [item['symbol'] for item in data][:top_n]

def get_upgraded_downgraded_symbols(symbols, api_key, debug=False, test_date=None):
    base_url = "https://financialmodelingprep.com/stable/grades"

    today = datetime.today().date()

    if test_date:
        # Force valid_dates to include the test_date
        valid_dates = [datetime.strptime(test_date, "%Y-%m-%d").date()]
    else:
        # valid_dates = [today]
        # Default: last 3 trading days
        valid_dates = []
        day = today
        while len(valid_dates) < 3:
           if day.weekday() < 5:
               valid_dates.append(day)
           day -= timedelta(days=1)

    if debug:
        print("Valid dates being checked:", valid_dates)

    result = []

    for symbol in symbols:
        try:
            url = f"{base_url}?symbol={symbol}&apikey={api_key}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if not data:
                if debug:
                    print(f"{symbol}: no data returned")
                continue

            latest = data[0]
            grade_date = datetime.strptime(latest["date"], "%Y-%m-%d").date()
            action = latest["action"].lower()

            if debug:
                print(f"{symbol}: latest_date={grade_date}, action={action}")

            if grade_date in valid_dates and action in ("upgrade", "downgrade"):
                result.append(symbol)

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    if debug:
        print("Final result:", result)

    return result


def get_top_grade_changes(symbols, api_key, top_n=3, debug=False):
    """
    Fetch the top N grade changes per symbol and return a combined DataFrame.

    Args:
        symbols (list): List of stock symbols.
        api_key (str): FMP API key.
        top_n (int): Number of top records to fetch per symbol.
        debug (bool): Print debug info if True.

    Returns:
        pd.DataFrame: Combined DataFrame of all symbols with top N grade changes.
    """
    base_url = "https://financialmodelingprep.com/stable/grades"
    all_records = []

    for symbol in symbols:
        try:
            url = f"{base_url}?symbol={symbol}&apikey={api_key}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if not data:
                if debug:
                    print(f"{symbol}: No data returned")
                continue

            # Take top N records
            for record in data[:top_n]:
                all_records.append(record)
                if debug:
                    print(record)

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    # Convert list of dictionaries to DataFrame
    df = pd.DataFrame(all_records)
    return df

def send_updates(test_date=None):
    
  top_100_tickers = fetch_sp500_symbols(top_n=100)
  api_key = API_KEY

  #matches = get_upgraded_downgraded_symbols(symbols, api_key,debug=True)
  #matches = get_upgraded_downgraded_symbols(top_100_tickers, api_key,debug=True, test_date="2025-09-15")
  matches = get_upgraded_downgraded_symbols(top_100_tickers, api_key,debug=False)

  symbols_to_check=matches
  df_grades = get_top_grade_changes(symbols_to_check, api_key, top_n=3, debug=False)
  #df_grades['fetch_date'] = datetime.today().strftime("%Y-%m-%d")  

  if os.path.exists(csv_path):
    df_old = pd.read_csv(csv_path)
    df_combined = pd.concat([df_old, df_grades], ignore_index=True)
    df_combined.drop_duplicates(inplace=True)
  else:
    df_combined = df_grades
  
  df_combined.to_csv(csv_path, index=False)    
  header = "`{:<6} {:<10} {:<12} {:<6}`".format(
    "Symbol", "Date","Company", "Action"
    )

  rows = [
    "`{:<6} {:<10} {:<12} {:<6}`".format(
        r.symbol, r.date,r.gradingCompany[:12], r.action[:6]
    )
    for r in df_grades.itertuples(index=False)
  ]

  message = "*Today's Stock Grading Updates:*\n\n" + "\n".join([header] + rows)


  url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
  payload = {
    "chat_id": CHAT_ID,
    "text": message,
    "parse_mode": "Markdown"
  }

  response = requests.post(url, data=payload)
  if response.status_code == 200:
    print("Message sent successfully!")
  else:
    print("Failed to send message:", response.text)


if __name__ == "__main__":
    test_date = None
    if len(sys.argv) > 1:
        test_date = sys.argv[1]  # first argument after script name
    send_updates(test_date=test_date)
