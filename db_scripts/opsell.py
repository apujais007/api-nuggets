import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

API_KEY = os.environ.get("FMP_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# =============================
# CONFIGURATION
# =============================

SCAN_CONFIG = {
    "min_iv_percentile": 5,          # Minimum acceptable IV percentile to consider volatility high enough
    "iv_filter_strict": 50,          # Stricter IV filter applied later before trade
    "drawdown_min": -9,              # Min 3-day drawdown (percentage)
    "drawdown_max": -3,              # Max 3-day drawdown (percentage)
    "dma_window": 50,                # Moving average window for price trend filter
    "rsi_min": 25,                   # Minimum RSI to avoid oversold extremes
    "max_5d_drop": -7,               # Max allowed 5-day drop before rejecting trade
    "max_10d_drop_for_regime": -7,   # Max 10-day drop to allow regime pass (soft stop)
    "hv_trend_threshold": 0,         # HV trend threshold to detect accelerating volatility
    "top_n": 3,                      # Number of top candidates to report
    "min_history": 260               # Minimum historical data points required
}

TICKER_UNIVERSE = [
    'NVDA', 'AAPL', 'GOOG', 'GOOGL', 'MSFT', 'AMZN', 'META', 'AVGO', 'TSLA', 'BRK-B',
    'LLY', 'WMT', 'JPM', 'V', 'ORCL', 'XOM', 'MA', 'JNJ', 'BAC', 'ABBV', 'NFLX',
    'PLTR', 'COST', 'AMD', 'MU', 'HD', 'GE', 'PG', 'CVX', 'WFC', 'UNH', 'CSCO',
    'KO', 'MS', 'GS', 'CAT', 'IBM', 'MRK', 'AXP', 'RTX', 'PM', 'CRM', 'LRCX',
    'TMO', 'TMUS', 'C', 'MCD', 'ABT', 'AMAT', 'APP', 'DIS', 'ISRG', 'LIN', 'PEP',
    'BX', 'QCOM', 'SCHW', 'GEV', 'AMGN', 'INTU', 'T', 'INTC', 'UBER', 'TJX', 'BKNG',
    'BA', 'APH', 'VZ', 'NEE', 'ANET', 'BLK', 'KLAC', 'DHR', 'ACN', 'TXN', 'COF',
    'SPGI', 'NOW', 'GILD', 'PFE', 'BSX', 'ADBE', 'LOW', 'UNP', 'ADI', 'SYK', 'WELL',
    'ETN', 'DE', 'PGR', 'HON', 'CB', 'MDT', 'COP', 'PANW', 'PLD', 'LMT', 'IBKR', 'VRTX', 'KKR',
    "XLB","XLC","XLY","XLP","XLE","XLF","XLV","XLI","XLRE","XLK","XLU","GLD","GBTC"
]

# =============================
# TELEGRAM MESSAGING
# =============================

def send_telegram_message(message: str):
    """
    Sends a message string to the configured Telegram chat via bot.
    This allows real-time alerts of accepted signals directly on Telegram.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, data=payload)
        if not response.ok:
            print(f"Telegram send error: {response.text}")
    except Exception as e:
        print(f"Exception sending Telegram message: {e}")

# =============================
# DATA FETCHING
# =============================

def get_price_data(symbol, limit=300):
    """
    Fetches historical price data for the given symbol from FMP.
    Sufficient recent data is needed to calculate indicators and run filters.
    """
    print(f"\n📥 Fetching data: {symbol}")
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?apikey={API_KEY}"
    r = requests.get(url)

    if r.status_code != 200:
        print("❌ API error")
        return None

    data = r.json().get("historical")
    if not data:
        print("❌ No historical data")
        return None

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    return df.tail(limit)

# =============================
# INDICATORS
# =============================

def calculate_hv(close, window=20):
    """
    Calculates Historical Volatility (HV) based on log returns.
    HV is a proxy for implied volatility (IV) used in options pricing.
    Higher HV indicates more option premium opportunity.
    """
    returns = np.log(close / close.shift(1))
    return returns.rolling(window).std() * np.sqrt(252)

def calculate_rsi(close, period=14):
    """
    Calculates the Relative Strength Index (RSI) to detect oversold/overbought conditions.
    We use it as a momentum filter to avoid entering during extreme selloffs.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_hv_percentile(df):
    """
    Calculates the percentile rank of the current HV compared to the past 252 trading days.
    Ensures current volatility is relatively high before selling options.
    """
    hv = calculate_hv(df["close"]).dropna().tail(252)
    if len(hv) < 100:
        return None

    current = hv.iloc[-1]
    percentile = (hv < current).mean() * 100
    print(f"IV (HV) Percentile: {percentile:.1f}")
    return percentile

# =============================
# CORE FILTERS
# =============================

def check_three_day_decline(df):
    """
    Checks if the last 3 days show a consistent decline.
    A sustained pullback increases chance of collecting premium on puts.
    """
    closes = df["close"].values
    decline = closes[-1] < closes[-2] < closes[-3]
    print(f"3-day closes: {closes[-3:]} → Decline={decline}")
    return decline

def check_drawdown(df):
    """
    Calculates the 3-day drawdown percentage and checks if it is within configured bounds.
    Ensures the pullback is meaningful but not too severe.
    """
    c0 = df["close"].iloc[-1]
    c3 = df["close"].iloc[-4]
    dd = (c0 / c3 - 1) * 100
    print(f"3-day drawdown: {dd:.2f}%")

    valid = SCAN_CONFIG["drawdown_min"] <= dd <= SCAN_CONFIG["drawdown_max"]
    return valid, dd

# =============================
# REGIME FILTER (SOFT STOP)
# =============================

def regime_filter(df):
    """
    Soft filter to reject signals during accelerating selloffs indicated by
    large 10-day drops with increasing volatility.
    Helps avoid getting trapped in worsening market conditions.
    """
    close = df["close"]

    ret_10d = (close.iloc[-1] / close.iloc[-11] - 1) * 100
    hv = calculate_hv(close)

    hv_trend = hv.iloc[-5:].mean() - hv.iloc[-15:-5].mean()

    print(f"10d return={ret_10d:.2f}%, HV trend={hv_trend:.4f}")

    if ret_10d < SCAN_CONFIG["max_10d_drop_for_regime"] and hv_trend > SCAN_CONFIG["hv_trend_threshold"]:
        return False, "Accelerating selloff"

    return True, "PASS"

# =============================
# HARD PRE-TRADE FILTER
# =============================

def pre_trade_filter(df, iv_percentile):
    """
    Hard stop filters just before trade execution including:
    - Price above moving average to confirm trend support
    - RSI above minimum threshold
    - Recent 5-day return not too negative
    - Sufficiently high implied volatility percentile
    """
    close = df["close"].iloc[-1]

    dma = df["close"].rolling(SCAN_CONFIG["dma_window"]).mean().iloc[-1]
    if close < dma:
        return False, f"Below {SCAN_CONFIG['dma_window']} DMA"

    rsi = calculate_rsi(df["close"]).iloc[-1]
    if rsi < SCAN_CONFIG["rsi_min"]:
        return False, f"RSI too low ({rsi:.1f})"

    ret_5d = (df["close"].iloc[-1] / df["close"].iloc[-6] - 1) * 100
    if ret_5d < SCAN_CONFIG["max_5d_drop"]:
        return False, f"5d drop too large ({ret_5d:.1f}%)"

    if iv_percentile < SCAN_CONFIG["iv_filter_strict"]:
        return False, f"IV too low ({iv_percentile:.0f})"

    return True, "PASS"

# =============================
# SIGNAL SCORING
# =============================

def score_signal(drawdown, ivp):
    """
    Generates a simple score combining magnitude of drawdown and IV percentile.
    Higher scores prioritize better premium opportunities.
    """
    return round(abs(drawdown) + ivp / 10, 2)

# =============================
# MAIN SCAN & TELEGRAM ALERT
# =============================
def run_daily_scan():
    signals_pass_all = []
    signals_except_iv_strict = []

    for symbol in TICKER_UNIVERSE:
        df = get_price_data(symbol)

        if df is None or len(df) < SCAN_CONFIG["min_history"]:
            continue

        if not check_three_day_decline(df):
            continue

        valid_dd, drawdown = check_drawdown(df)
        if not valid_dd:
            continue

        ivp = calculate_hv_percentile(df)
        if ivp is None or ivp < SCAN_CONFIG["min_iv_percentile"]:
            continue

        ok, reason = regime_filter(df)
        if not ok:
            continue

        # Run all filters except strict IV filter first
        ok_pre_trade, reason_pre_trade = pre_trade_filter(df, ivp)

        # Inside loop over symbols:
        ok_pre_trade, reason_pre_trade = pre_trade_filter(df, ivp)

        if not ok_pre_trade and "IV too low" in reason_pre_trade:
            signals_except_iv_strict.append({
                "symbol": symbol,
                "drawdown_pct": round(drawdown, 2),
                "iv_percentile": round(ivp, 1),
                "score": score_signal(drawdown, ivp),
                "reason": reason_pre_trade
            })
            continue

        if not ok_pre_trade:
            continue

        signals_pass_all.append({
            "symbol": symbol,
            "drawdown_pct": round(drawdown, 2),
            "iv_percentile": round(ivp, 1),
            "score": score_signal(drawdown, ivp)
        })

        time.sleep(0.6)

    # Sort signals
    signals_pass_all = sorted(signals_pass_all, key=lambda x: x["score"], reverse=True)
    signals_except_iv_strict = sorted(signals_except_iv_strict, key=lambda x: x["score"], reverse=True)

    # Print and send Telegram messages

    if signals_pass_all:
        print("\n🔥 TOP OPTIONS SELLING CANDIDATES (PASS ALL FILTERS) 🔥")
        for s in signals_pass_all[:SCAN_CONFIG["top_n"]]:
            print(s)

        msg_lines = ["🔥 *Top Options Selling Candidates (Pass All Filters):* 🔥\n"]
        for s in signals_pass_all[:SCAN_CONFIG["top_n"]]:
            msg_lines.append(f"{s['symbol']}: Drawdown {s['drawdown_pct']}%, IV Percentile {s['iv_percentile']}, Score {s['score']}")
        send_telegram_message("\n".join(msg_lines))
    else:
        print("🚫 No signals passing all filters")
        send_telegram_message("🚫 No signals passing all filters")

    if signals_except_iv_strict:
        print("\n⚠️ CANDIDATES PASSING ALL BUT STRICT IV FILTER ⚠️")
        for s in signals_except_iv_strict[:SCAN_CONFIG["top_n"]]:
            print(s)

        msg_lines = ["⚠️ *Candidates Passing All But Strict IV Filter:* ⚠️\n"]
        for s in signals_except_iv_strict[:SCAN_CONFIG["top_n"]]:
            msg_lines.append(f"{s['symbol']}: Drawdown {s['drawdown_pct']}%, IV Percentile {s['iv_percentile']} (Below Strict Threshold), Score {s['score']}")
        send_telegram_message("\n".join(msg_lines))

# =============================
# ENTRY POINT
# =============================

if __name__ == "__main__":
    run_daily_scan()
