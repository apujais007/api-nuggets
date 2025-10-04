import os
import requests
import pandas as pd

API_KEY = os.environ.get("FMP_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

def fetch_sp500_symbols():
    url = f"https://financialmodelingprep.com/api/v3/sp500_constituent?apikey={API_KEY}"
    data = requests.get(url).json()
    return [item["symbol"] for item in data]

def fetch_quotes(symbols, chunk_size=50):
    quotes = []
    for i in range(0, len(symbols), chunk_size):
        chunk = ",".join(symbols[i:i+chunk_size])
        url = f"https://financialmodelingprep.com/api/v3/quote/{chunk}?apikey={API_KEY}"
        data = requests.get(url).json()
        quotes.extend(data)
    return quotes

def prepare_top_movers(df, top_n=10):
    df["changesPercentage"] = pd.to_numeric(df["changesPercentage"], errors="coerce")
    #df = df.rename(columns={"changesPercentage": "age"})

    top_gainers = df.sort_values("changesPercentage", ascending=False).head(top_n)
    top_losers = df.sort_values("changesPercentage", ascending=True).head(top_n)

    return top_gainers, top_losers
   

def df_to_telegram_table(df, title):
    header = "`{:<8} {:<10} {:<10} {:<8}`".format("Symbol", "Price", "Change", "%age")
    rows = [
        "`{:<8} {:<10.2f} {:<10.2f} {:<8.2f}`".format(
            r.symbol, r.price, r.change, r._asdict().get("changesPercentage", 0)
        )
        for r in df.itertuples(index=False)
    ]
    message = f"*{title}:*\n\n" + "\n".join([header] + rows)
    return message

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        print("Telegram send failed:", r.text)

def main():
    symbols = fetch_sp500_symbols()
    quotes = fetch_quotes(symbols)
    df = pd.DataFrame(quotes)

    top_gainers, top_losers = prepare_top_movers(df)

    msg_gainers = df_to_telegram_table(top_gainers, "Top 10 Gainers in S&P500")
    msg_losers = df_to_telegram_table(top_losers, "Top 10 Losers in S&P500")

    send_telegram_message(msg_gainers)
    send_telegram_message(msg_losers)

if __name__ == "__main__":
    main()
