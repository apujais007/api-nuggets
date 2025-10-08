import os
import sys
import requests
import pandas as pd
from datetime import datetime, timedelta, date

excel_path = "data/grades_updates.xlsx"
os.makedirs(os.path.dirname(excel_path), exist_ok=True)

API_KEY = os.environ.get("FMP_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
    
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

# -------------------------------
# FUNCTION: Fetch price target trend
# -------------------------------
def fetch_price_target_trend(symbol):
    url = f"https://financialmodelingprep.com/stable/price-target-news?symbol={symbol}&page=0&limit=10&apikey={API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            print(f"Error fetching {symbol}: {response.status_code}")
            return None
        data = response.json()
        if not data or len(data) < 2:
            return None

        # Sort by date descending and take latest 2
        data_sorted = sorted(data, key=lambda x: x["publishedDate"], reverse=True)[:2]
        latest = data_sorted[0]
        previous = data_sorted[1]

        latest_target = latest.get("priceTarget") or latest.get("adjPriceTarget")
        prev_target = previous.get("priceTarget") or previous.get("adjPriceTarget")
        if latest_target is None or prev_target is None:
            return None

        if latest_target > prev_target:
            trend = "Raised"
        elif latest_target < prev_target:
            trend = "Lowered"
        else:
            trend = "Unchanged"

        def clean_date(dt_str):
            return datetime.fromisoformat(dt_str.replace("Z", "")).strftime("%Y-%m-%d")

        return {
            "Symbol": symbol,
            "Latest_Date": clean_date(latest["publishedDate"]),
            "Latest_Analyst": latest.get("analystName"),
            "Latest_Firm": latest.get("analystCompany"),
            "Latest_Target": latest_target,
            "Previous_Date": clean_date(previous["publishedDate"]),
            "Previous_Analyst": previous.get("analystName"),
            "Previous_Firm": previous.get("analystCompany"),
            "Previous_Target": prev_target,
            "Trend": trend
        }
    except Exception as e:
        print(f"Error processing {symbol}: {e}")
        return None

def fmt_date(date_str):
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", ""))
        return dt.strftime("%b %-d")  # 'Oct 3'
    except:
        return date_str

def trend_arrow(trend):
    if trend == "Raised":
        return "↑"
    elif trend == "Lowered":
        return "↓"
    else:
        return "→"
        
def send_updates(test_date=None):
    top_100_tickers = fetch_sp500_symbols(top_n=100)
    matched_symbols = get_upgraded_downgraded_symbols(top_100_tickers, API_KEY, debug=False, test_date=test_date)

    if not matched_symbols:
        print("No upgrades/downgrades found.")
        return

    # -----------------------------
    # Grades updates
    # -----------------------------
    df_grades = get_top_grade_changes(matched_symbols, API_KEY, top_n=3, debug=False)

    if os.path.exists(excel_path):
        df_old = pd.read_excel(excel_path, sheet_name="Grades Updates")
        df_combined = pd.concat([df_old, df_grades], ignore_index=True)
        df_combined.drop_duplicates(inplace=True)
    else:
        df_combined = df_grades
        
    # Save grades to Excel (first tab)
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_combined.to_excel(writer, sheet_name="Grades Updates", index=False)

    # -----------------------------
    # Send Grades Updates to Telegram
    # -----------------------------
    if not df_grades.empty:
        header = "`{:<6} {:<10} {:<12} {:<6}`".format("Symbol", "Date", "Company", "Action")
        rows = [
            "`{:<6} {:<10} {:<12} {:<6}`".format(r.symbol, r.date, r.gradingCompany[:12], r.action[:6])
            for r in df_grades.itertuples(index=False)
        ]
        message_grades = "*Today's Stock Grading Updates:*\n\n" + "\n".join([header] + rows)

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message_grades, "parse_mode": "Markdown"}
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("Grades message sent successfully!")
        else:
            print("Failed to send grades message:", response.text)

    # -----------------------------
    # Price Target Trend
    # -----------------------------
    trend_records = []
    for sym in matched_symbols:
        trend = fetch_price_target_trend(sym)
        if trend:
            trend_records.append(trend)

    df_trends = pd.DataFrame(trend_records) if trend_records else pd.DataFrame()

    # Save price trend in second tab
    if not df_trends.empty:
        with pd.ExcelWriter(excel_path, engine="openpyxl", mode="a") as writer:
            df_trends.to_excel(writer, sheet_name="Price Target Trend", index=False)

        # Send Price Target Trend to Telegram
    header_trend = "`{:<6} {:<6} {:<8} {:<5} {:<5} {:<1}`".format(
        "Symbol", "N.Dt", "Firm", "N.Tgt", "O.Tgt", "T"
    )

    # Rows
    rows_trend = [
        "`{:<6} {:<6} {:<8} {:<5} {:<5} {:<1}`".format(
            r.Symbol,
            fmt_date(r.Latest_Date),
            (r.Latest_Firm or "")[:8],  # truncate firm name
            r.Latest_Target,
            r.Previous_Target,
            trend_arrow(r.Trend)
        )
        for r in df_trends.itertuples(index=False)
    ]            
    message_trend = "*Price Target Trend Summary:*\n\n" + "\n".join([header_trend] + rows_trend)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message_trend, "parse_mode": "Markdown"}
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print("Price trend message sent successfully!")
    else:
        print("Failed to send price trend message:", response.text)


if __name__ == "__main__":
    test_date = None
    if len(sys.argv) > 1:
        test_date = sys.argv[1]
    send_updates(test_date=test_date)
