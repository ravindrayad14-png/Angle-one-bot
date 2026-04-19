import time
import datetime
import logging
from SmartApi import SmartConnect
import pyotp

# ============================================================
# CONFIGURATION - Fill these in Railway environment variables
# ============================================================
import os

API_KEY = os.environ.get("API_KEY", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")
PASSWORD = os.environ.get("PASSWORD", "")
TOTP_SECRET = os.environ.get("TOTP_SECRET", "")

# Trading settings
CAPITAL = float(os.environ.get("CAPITAL", "10000"))
POSITION_SIZE = 0.15  # 15% of capital per trade
MAX_LOSS_PCT = 0.02   # 2% stop loss
TAKE_PROFIT_PCT = 0.04  # 4% take profit

# Stocks to trade (NSE)
WATCHLIST = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK",
    "ICICIBANK", "WIPRO", "SBIN", "TATAMOTORS"
]

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ============================================================
# CONNECT TO ANGEL ONE
# ============================================================
def connect():
    try:
        obj = SmartConnect(api_key=API_KEY)
        totp = pyotp.TOTP(TOTP_SECRET).now()
        data = obj.generateSession(CLIENT_ID, PASSWORD, totp)
        if data["status"]:
            log.info(f"✅ Connected to Angel One | Client: {CLIENT_ID}")
            return obj
        else:
            log.error(f"❌ Login failed: {data}")
            return None
    except Exception as e:
        log.error(f"❌ Connection error: {e}")
        return None

# ============================================================
# GET LIVE PRICE
# ============================================================
def get_price(obj, symbol):
    try:
        # Token map for common NSE stocks
        token_map = {
            "RELIANCE": "2885", "TCS": "11536", "INFY": "1594",
            "HDFCBANK": "1333", "ICICIBANK": "4963", "WIPRO": "3787",
            "SBIN": "3045", "TATAMOTORS": "3456"
        }
        token = token_map.get(symbol)
        if not token:
            return None
        data = obj.ltpData("NSE", symbol + "-EQ", token)
        if data["status"]:
            return float(data["data"]["ltp"])
        return None
    except Exception as e:
        log.error(f"Price error for {symbol}: {e}")
        return None

# ============================================================
# GET CANDLE DATA FOR INDICATORS
# ============================================================
def get_candles(obj, symbol):
    try:
        token_map = {
            "RELIANCE": "2885", "TCS": "11536", "INFY": "1594",
            "HDFCBANK": "1333", "ICICIBANK": "4963", "WIPRO": "3787",
            "SBIN": "3045", "TATAMOTORS": "3456"
        }
        token = token_map.get(symbol)
        now = datetime.datetime.now()
        from_date = (now - datetime.timedelta(days=5)).strftime("%Y-%m-%d %H:%M")
        to_date = now.strftime("%Y-%m-%d %H:%M")
        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": "FIFTEEN_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }
        data = obj.getCandleData(params)
        if data["status"] and data["data"]:
            closes = [float(c[4]) for c in data["data"]]
            return closes
        return []
    except Exception as e:
        log.error(f"Candle error for {symbol}: {e}")
        return []

# ============================================================
# INDICATORS
# ============================================================
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    changes = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [c for c in changes[-period:] if c > 0]
    losses = [abs(c) for c in changes[-period:] if c < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ma(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0
    return sum(prices[-period:]) / period

def get_signal(prices):
    if len(prices) < 22:
        return "HOLD"
    rsi = calc_rsi(prices)
    ma9 = calc_ma(prices, 9)
    ma21 = calc_ma(prices, 21)
    current = prices[-1]
    if rsi < 35 and current > ma9 and ma9 > ma21:
        return "BUY"
    if rsi > 65 and current < ma9 and ma9 < ma21:
        return "SELL"
    return "HOLD"

# ============================================================
# PLACE ORDER
# ============================================================
def place_order(obj, symbol, action, qty):
    try:
        token_map = {
            "RELIANCE": "2885", "TCS": "11536", "INFY": "1594",
            "HDFCBANK": "1333", "ICICIBANK": "4963", "WIPRO": "3787",
            "SBIN": "3045", "TATAMOTORS": "3456"
        }
        order = {
            "variety": "NORMAL",
            "tradingsymbol": symbol + "-EQ",
            "symboltoken": token_map[symbol],
            "transactiontype": action,  # "BUY" or "SELL"
            "exchange": "NSE",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": qty
        }
        response = obj.placeOrder(order)
        log.info(f"✅ Order placed | {action} {qty} {symbol} | ID: {response}")
        return response
    except Exception as e:
        log.error(f"❌ Order failed for {symbol}: {e}")
        return None

# ============================================================
# MARKET HOURS CHECK
# ============================================================
def is_market_open():
    now = datetime.datetime.now()
    # Skip weekends
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0)
    market_close = now.replace(hour=15, minute=20, second=0)
    return market_open <= now <= market_close

def is_closing_time():
    now = datetime.datetime.now()
    closing = now.replace(hour=15, minute=10, second=0)
    return now >= closing

# ============================================================
# MAIN BOT LOOP
# ============================================================
def run_bot():
    log.info("🤖 AngelOne Trading Bot Starting...")
    log.info(f"💰 Capital: ₹{CAPITAL} | Stocks: {', '.join(WATCHLIST)}")

    obj = connect()
    if not obj:
        log.error("Failed to connect. Retrying in 60s...")
        time.sleep(60)
        return run_bot()

    portfolio = {}  # {symbol: {qty, buy_price}}

    while True:
        try:
            if not is_market_open():
                log.info("⏰ Market closed. Waiting...")
                time.sleep(300)  # Check every 5 min
                continue

            # Close all positions at end of day
            if is_closing_time() and portfolio:
                log.info("🔔 Market closing — squaring off all positions")
                for symbol, pos in list(portfolio.items()):
                    place_order(obj, symbol, "SELL", pos["qty"])
                    del portfolio[symbol]
                    log.info(f"📤 Squared off {symbol}")
                time.sleep(600)
                continue

            available_capital = CAPITAL - sum(
                p["buy_price"] * p["qty"] for p in portfolio.values()
            )

            for symbol in WATCHLIST:
                try:
                    prices = get_candles(obj, symbol)
                    if not prices:
                        continue

                    price = get_price(obj, symbol)
                    if not price:
                        continue

                    signal = get_signal(prices)
                    rsi = calc_rsi(prices)
                    log.info(f"{symbol} | ₹{price:.2f} | RSI: {rsi:.1f} | Signal: {signal}")

                    # BUY logic
                    if signal == "BUY" and symbol not in portfolio:
                        qty = int((available_capital * POSITION_SIZE) / price)
                        if qty > 0 and available_capital >= price * qty:
                            order_id = place_order(obj, symbol, "BUY", qty)
                            if order_id:
                                portfolio[symbol] = {"qty": qty, "buy_price": price}
                                available_capital -= price * qty
                                log.info(f"🟢 BUY {qty} {symbol} @ ₹{price:.2f}")

                    # SELL logic
                    elif symbol in portfolio:
                        pos = portfolio[symbol]
                        pnl_pct = (price - pos["buy_price"]) / pos["buy_price"]

                        should_sell = (
                            signal == "SELL" or
                            pnl_pct <= -MAX_LOSS_PCT or      # Stop loss
                            pnl_pct >= TAKE_PROFIT_PCT        # Take profit
                        )

                        if should_sell:
                            reason = "SIGNAL" if signal == "SELL" else ("STOP LOSS" if pnl_pct < 0 else "TAKE PROFIT")
                            order_id = place_order(obj, symbol, "SELL", pos["qty"])
                            if order_id:
                                pnl = (price - pos["buy_price"]) * pos["qty"]
                                log.info(f"🔴 SELL {pos['qty']} {symbol} @ ₹{price:.2f} | P&L: ₹{pnl:.2f} | Reason: {reason}")
                                del portfolio[symbol]

                    time.sleep(1)  # Small delay between stocks

                except Exception as e:
                    log.error(f"Error processing {symbol}: {e}")
                    continue

            log.info(f"📊 Portfolio: {list(portfolio.keys())} | Capital used: ₹{CAPITAL - available_capital:.2f}")
            log.info("⏳ Waiting 15 minutes for next candle...")
            time.sleep(900)  # Wait 15 minutes

        except Exception as e:
            log.error(f"Bot error: {e}. Reconnecting...")
            time.sleep(30)
            obj = connect()

if __name__ == "__main__":
    run_bot()
