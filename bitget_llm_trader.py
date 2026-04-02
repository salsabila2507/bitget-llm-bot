import time, logging, json, requests, hmac, hashlib, base64, math, threading, sqlite3
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('/root/bitget_bot.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

API_KEY = "YOUR_BITGET_API_KEY"
SECRET_KEY = "YOUR_BITGET_SECRET_KEY"
PASSPHRASE = "YOUR_BITGET_PASSPHRASE"
BASE_URL = "https://api.bitget.com"
GROQ_API_KEY = "YOUR_GROQ_API_KEY"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
LLM_MODEL = "llama-3.3-70b-versatile"
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID"

MIN_NOTIONAL, MAX_PRICE = 5.5, 1.0
MIN_LEVERAGE, MAX_LEVERAGE = 10, 30
MARGIN_MODE, PRODUCT_TYPE, MARGIN_COIN = "isolated", "USDT-FUTURES", "USDT"
SLEEP_MINUTES = 15

MAX_POSITIONS, MAX_NOTIONAL_PCT = 2, 40.0
STOP_LOSS_PCT, TAKE_PROFIT_USD = 10.0, 0.50
MAX_DAILY_LOSS_USD, TRADE_COOLDOWN_MIN = 0.30, 10
TRAILING_STOP_PCT, MIN_CONFIDENCE = 3.0, 75
CONSECUTIVE_LOSS_LIMIT = 3
TIMEFRAMES = ["15m", "1H", "4H"]
DB_PATH = "/root/trade_history.db"

bot_running, force_trade, last_update_id = True, False, 0
last_trade_time, daily_pnl = 0, 0.0
trailing_stops, consecutive_losses, blacklisted_pairs = {}, 0, set()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, action TEXT, entry_price REAL,
        exit_price REAL, size REAL, pnl REAL, leverage INTEGER,
        confidence INTEGER, opened_at TEXT, closed_at TEXT)''')
    conn.commit()
    conn.close()

def save_trade_open(symbol, action, entry_price, size, leverage, confidence):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO trades (symbol, action, entry_price, size, leverage, confidence, opened_at) VALUES (?,?,?,?,?,?,?)",
        (symbol, action, entry_price, size, leverage, confidence, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def save_trade_close(symbol, exit_price, pnl):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=? WHERE symbol=? AND closed_at IS NULL",
        (exit_price, pnl, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), symbol))
    conn.commit()
    conn.close()

def get_trade_summary():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT * FROM trades WHERE closed_at IS NOT NULL ORDER BY closed_at DESC")
        rows = cur.fetchall()
        conn.close()
        if not rows: return None
        total = len(rows)
        wins = sum(1 for r in rows if r[6] and r[6] > 0)
        avg_pnl = sum(r[6] for r in rows if r[6]) / total
        sym_pnl = {}
        for r in rows:
            if r[6]: sym_pnl[r[1]] = sym_pnl.get(r[1], 0) + r[6]
        best = max(sym_pnl.items(), key=lambda x: x[1])[0] if sym_pnl else "N/A"
        worst = min(sym_pnl.items(), key=lambda x: x[1])[0] if sym_pnl else "N/A"
        last_10 = "\n".join([f"{'✅' if r[6]>0 else '❌'} {r[1]} {r[2]} | PnL: {r[6]:.4f}" for r in rows[:10]])
        return {"total_trades": total, "win_rate": f"{wins/total*100:.1f}%", "avg_pnl": f"{avg_pnl:.4f}",
                "best_pair": best, "worst_pair": worst, "last_10": last_10}
    except: return None

def get_today_pnl():
    try:
        conn = sqlite3.connect(DB_PATH)
        today = datetime.now().strftime("%Y-%m-%d")
        cur = conn.execute("SELECT SUM(pnl) FROM trades WHERE closed_at LIKE ? AND pnl IS NOT NULL", (f"{today}%",))
        result = cur.fetchone()[0]
        conn.close()
        return result if result else 0.0
    except: return 0.0

def get_pair_performance(symbol):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), AVG(pnl) FROM trades WHERE symbol=? AND closed_at IS NOT NULL", (symbol,))
        row = cur.fetchone()
        conn.close()
        if not row or row[0] == 0: return None
        total_trades, wins, avg_pnl = row[0], row[1], row[2]
        win_rate = (wins / total_trades) * 100
        return {"total": total_trades, "win_rate": win_rate, "avg_pnl": avg_pnl}
    except: return None

def get_learning_context():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT symbol, action, pnl, confidence FROM trades WHERE closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT 20")
        rows = cur.fetchall()
        conn.close()
        if not rows: return "No trade history yet."
        losing_pairs = defaultdict(int)
        winning_pairs = defaultdict(int)
        for row in rows:
            symbol, action, pnl, conf = row
            if pnl < 0: losing_pairs[symbol] += 1
            else: winning_pairs[symbol] += 1
        context = "Recent trade patterns:\n"
        if losing_pairs:
            worst = sorted(losing_pairs.items(), key=lambda x: x[1], reverse=True)[:3]
            context += f"Pairs with most losses: {', '.join([f'{p[0]} ({p[1]}x)' for p in worst])}\n"
        if winning_pairs:
            best = sorted(winning_pairs.items(), key=lambda x: x[1], reverse=True)[:3]
            context += f"Pairs with most wins: {', '.join([f'{p[0]} ({p[1]}x)' for p in best])}\n"
        context += f"\nLast 5 trades:\n"
        for row in rows[:5]:
            symbol, action, pnl, conf = row
            result = "WIN" if pnl > 0 else "LOSS"
            context += f"- {symbol} {action} | {result} ({pnl:.4f} USDT) | Conf: {conf}%\n"
        return context
    except: return "No learning context available."

def update_blacklist():
    global blacklisted_pairs
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""SELECT symbol, COUNT(*) as total, SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses
            FROM trades WHERE closed_at IS NOT NULL GROUP BY symbol HAVING total >= 5""")
        rows = cur.fetchall()
        conn.close()
        blacklisted_pairs.clear()
        for row in rows:
            symbol, total, losses = row
            loss_rate = (losses / total) * 100
            if loss_rate > 70:
                blacklisted_pairs.add(symbol)
                logger.warning(f"Blacklisted {symbol} (loss rate: {loss_rate:.1f}%)")
    except: pass

def sign(method, path, body=""):
    ts = str(int(time.time() * 1000))
    msg = ts + method.upper() + path + (body if body else "")
    sig = base64.b64encode(hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"ACCESS-KEY": API_KEY, "ACCESS-SIGN": sig, "ACCESS-TIMESTAMP": ts, "ACCESS-PASSPHRASE": PASSPHRASE, "Content-Type": "application/json"}

def api_get(path):
    try:
        r = requests.get(BASE_URL + path, headers=sign("GET", path), timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"api_get {path} error: {e}")
        return {}

def api_post(path, body):
    try:
        body_str = json.dumps(body)
        r = requests.post(BASE_URL + path, headers=sign("POST", path, body_str), data=body_str, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"api_post {path} error: {e}")
        return {}

def get_balance():
    res = api_get(f"/api/v2/mix/account/accounts?productType={PRODUCT_TYPE}")
    if res.get("code") != "00000": return 0.0
    accs = res.get("data", [])
    for a in accs:
        if a.get("marginCoin") == MARGIN_COIN:
            return float(a.get("available", 0))
    return 0.0

def get_positions():
    res = api_get(f"/api/v2/mix/position/all-position?productType={PRODUCT_TYPE}&marginCoin={MARGIN_COIN}")
    if res.get("code") != "00000": return []
    return res.get("data", [])

def get_tickers():
    res = api_get(f"/api/v2/mix/market/tickers?productType={PRODUCT_TYPE}")
    if res.get("code") != "00000": return []
    return res.get("data", [])

def get_candles(symbol, interval="15m", limit=100):
    path = f"/api/v2/mix/market/candles?symbol={symbol}&productType={PRODUCT_TYPE}&granularity={interval}&limit={limit}"
    res = api_get(path)
    if res.get("code") != "00000": return []
    return res.get("data", [])

def set_leverage(symbol, leverage, hold_side="long"):
    body = {"symbol": symbol, "productType": PRODUCT_TYPE, "marginCoin": MARGIN_COIN, "leverage": str(leverage), "holdSide": hold_side}
    return api_post("/api/v2/mix/account/set-leverage", body)

def place_order(symbol, side, size, hold_side="long"):
    body = {"symbol": symbol, "productType": PRODUCT_TYPE, "marginMode": MARGIN_MODE, "marginCoin": MARGIN_COIN,
            "size": str(size), "side": side, "tradeSide": "open", "orderType": "market", "holdSide": hold_side}
    return api_post("/api/v2/mix/order/place-order", body)

def close_position_api(symbol, hold_side="long"):
    body = {"symbol": symbol, "productType": PRODUCT_TYPE, "holdSide": hold_side}
    return api_post("/api/v2/mix/order/close-positions", body)

def close_all_positions():
    positions = get_positions()
    for p in positions:
        symbol, hold, pnl, price = p["symbol"], p.get("holdSide", "long"), float(p.get("unrealizedPL", 0)), float(p.get("markPrice", 0))
        res = close_position_api(symbol, hold)
        if res.get("code") == "00000":
            save_trade_close(symbol, price, pnl)
            emoji = "✅" if pnl > 0 else "❌"
            send_telegram(f"{emoji} <b>CLOSED</b> {hold.upper()} {symbol}\nPnL: <b>{pnl:.4f} USDT</b>")
            logger.info(f"Closed {hold} {symbol} | PnL: {pnl:.4f}")

def send_telegram(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except: pass

def get_telegram_updates():
    global last_update_id
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 5}, timeout=10)
        updates = r.json().get("result", [])
        if updates: last_update_id = updates[-1]["update_id"]
        return updates
    except: return []

def ask_llm(prompt):
    try:
        r = requests.post(f"{GROQ_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": LLM_MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 600}, timeout=30)
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return None

def analyze_with_learning(symbol):
    perf = get_pair_performance(symbol)
    if perf and perf["win_rate"] < 30:
        logger.info(f"Skipping {symbol} - poor history (WR: {perf['win_rate']:.1f}%)")
        return None
    candle_data = {}
    for tf in TIMEFRAMES:
        candles = get_candles(symbol, tf, 50)
        if candles: candle_data[tf] = candles[:10]
    if not candle_data: return None
    learning_context = get_learning_context()
    prompt = f"""You are an expert crypto trader. Analyze {symbol} and learn from past mistakes.

=== LEARNING CONTEXT ===
{learning_context}

=== CURRENT MARKET DATA ===
"""
    for tf, candles in candle_data.items():
        prompt += f"\n{tf} timeframe (last 10 candles - [timestamp, open, high, low, close, volume]):\n"
        for c in candles[:5]: prompt += f"{c}\n"
    if perf:
        prompt += f"\n=== {symbol} HISTORICAL PERFORMANCE ===\n"
        prompt += f"Total trades: {perf['total']} | Win rate: {perf['win_rate']:.1f}% | Avg PnL: {perf['avg_pnl']:.4f}\n"
    prompt += f"""
CRITICAL RULES:
1. Learn from past losses - avoid similar setups
2. Be EXTREMELY conservative (capital is only $1)
3. Only trade HIGH conviction setups (75%+ confidence)
4. Skip if trend unclear or contradictory signals
5. Prefer pairs with proven win rate

Analysis steps:
1. Check trend alignment across 15m/1H/4H
2. Identify support/resistance
3. Volume confirmation
4. Compare with past losing trades - avoid similar patterns
5. Risk/reward must be >2:1

Respond EXACTLY in this format:
DECISION: LONG/SHORT/SKIP
CONFIDENCE: 0-100
REASONING: Brief explanation (mention if avoiding past mistakes)
LEVERAGE: {MIN_LEVERAGE}-{MAX_LEVERAGE}
"""
    response = ask_llm(prompt)
    if not response: return None
    try:
        lines = response.strip().split("\n")
        data = {}
        for line in lines:
            if ":" in line:
                key, val = line.split(":", 1)
                data[key.strip().upper()] = val.strip()
        decision = data.get("DECISION", "SKIP").upper()
        if decision not in ["LONG", "SHORT", "SKIP"]: return None
        confidence = int(data.get("CONFIDENCE", "0"))
        if confidence < MIN_CONFIDENCE:
            logger.info(f"{symbol} - Low confidence: {confidence}%")
            return None
        leverage = int(data.get("LEVERAGE", str(MIN_LEVERAGE)))
        leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, leverage))
        return {"decision": decision, "confidence": confidence, "reasoning": data.get("REASONING", ""), "leverage": leverage}
    except: return None

def calculate_position_size(balance, leverage, entry_price):
    max_notional = balance * (MAX_NOTIONAL_PCT / 100)
    size = (max_notional * leverage) / entry_price
    return math.floor(size * 100) / 100

def check_stop_loss(position, entry_price):
    current_price = float(position.get("markPrice", 0))
    hold_side = position.get("holdSide", "long")
    if hold_side == "long":
        loss_pct = ((current_price - entry_price) / entry_price) * 100
    else:
        loss_pct = ((entry_price - current_price) / entry_price) * 100
    return loss_pct <= -STOP_LOSS_PCT

def check_trailing_stop(symbol, current_pnl):
    if current_pnl <= 0: return False
    if symbol not in trailing_stops:
        trailing_stops[symbol] = current_pnl
        return False
    highest = trailing_stops[symbol]
    if current_pnl > highest:
        trailing_stops[symbol] = current_pnl
        return False
    drawdown_pct = ((highest - current_pnl) / highest) * 100
    return drawdown_pct >= TRAILING_STOP_PCT

def find_and_trade():
    global last_trade_time, daily_pnl, force_trade, consecutive_losses
    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
        logger.warning(f"Paused - {consecutive_losses} consecutive losses")
        send_telegram(f"⚠️ <b>Auto-paused</b>\n{consecutive_losses} consecutive losses\nUse /trade to resume")
        return
    daily_pnl = get_today_pnl()
    if daily_pnl <= -MAX_DAILY_LOSS_USD:
        logger.warning(f"Daily loss limit hit: {daily_pnl:.4f} USDT")
        send_telegram(f"🛑 <b>DAILY LOSS LIMIT</b>\nPnL: {daily_pnl:.4f} USDT\nPaused until tomorrow.")
        return
    positions = get_positions()
    if len(positions) >= MAX_POSITIONS:
        logger.info(f"Max positions reached: {len(positions)}/{MAX_POSITIONS}")
        return
    if not force_trade:
        elapsed = (time.time() - last_trade_time) / 60
        if elapsed < TRADE_COOLDOWN_MIN:
            logger.info(f"Cooldown: {TRADE_COOLDOWN_MIN - elapsed:.1f} min remaining")
            return
    force_trade = False
    balance = get_balance()
    if balance < 0.10:
        logger.warning(f"Balance too low: {balance:.4f} USDT")
        send_telegram(f"⚠️ Balance too low: {balance:.4f} USDT")
        return
    update_blacklist()
    tickers = get_tickers()
    candidates = [t for t in tickers if float(t.get("lastPr", 999)) < MAX_PRICE and float(t.get("baseVolume", 0)) > 0 and t["symbol"] not in blacklisted_pairs]
    if not candidates:
        logger.info("No candidates found")
        return
    candidates = sorted(candidates, key=lambda x: float(x.get("baseVolume", 0)), reverse=True)[:3]
    for ticker in candidates:
        symbol = ticker["symbol"]
        if symbol in [p["symbol"] for p in positions]: continue
        logger.info(f"Analyzing {symbol}...")
        analysis = analyze_with_learning(symbol)
        if not analysis or analysis["decision"] == "SKIP": continue
        decision, leverage, confidence, reasoning = analysis["decision"], analysis["leverage"], analysis["confidence"], analysis["reasoning"]
        hold_side = "long" if decision == "LONG" else "short"
        set_leverage(symbol, leverage, hold_side)
        price = float(ticker.get("lastPr", 0))
        size = calculate_position_size(balance, leverage, price)
        notional = size * price
        if notional < MIN_NOTIONAL or notional > balance * (MAX_NOTIONAL_PCT / 100):
            logger.warning(f"Invalid notional for {symbol}: {notional:.4f}")
            continue
        side = "buy" if decision == "LONG" else "sell"
        res = place_order(symbol, side, size, hold_side)
        if res.get("code") == "00000":
            save_trade_open(symbol, decision, price, size, leverage, confidence)
            last_trade_time = time.time()
            msg = (f"🟢 <b>{decision} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
                   f"Size: <b>{size}</b> | Notional: <b>{notional:.2f} USDT</b>\nLeverage: <b>{leverage}x</b>\n"
                   f"Confidence: <b>{confidence}%</b>\nTarget TP: <b>{TAKE_PROFIT_USD} USDT</b>\nSL: <b>-{STOP_LOSS_PCT}%</b>\n\n💡 {reasoning}")
            send_telegram(msg)
            logger.info(f"Opened {decision} {symbol} @ {price} | Size: {size} | Lev: {leverage}x")
            return
        else:
            logger.error(f"Order failed for {symbol}: {res.get('msg')}")
    logger.info("No valid setup found")

def manage_positions():
    global consecutive_losses
    positions = get_positions()
    if not positions: return
    for p in positions:
        symbol, hold_side, pnl, entry, current = p["symbol"], p.get("holdSide", "long"), float(p.get("unrealizedPL", 0)), float(p.get("openPriceAvg", 0)), float(p.get("markPrice", 0))
        if pnl >= TAKE_PROFIT_USD:
            res = close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close(symbol, current, pnl)
                if symbol in trailing_stops: del trailing_stops[symbol]
                consecutive_losses = 0
                send_telegram(f"✅ <b>TAKE PROFIT</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nPnL: <b>+{pnl:.4f} USDT</b>")
                logger.info(f"TP hit {symbol} | PnL: {pnl:.4f}")
                continue
        if check_stop_loss(p, entry):
            res = close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close(symbol, current, pnl)
                if symbol in trailing_stops: del trailing_stops[symbol]
                consecutive_losses += 1
                send_telegram(f"🛑 <b>STOP LOSS</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nPnL: <b>{pnl:.4f} USDT</b>\nConsecutive losses: {consecutive_losses}")
                logger.info(f"SL hit {symbol} | PnL: {pnl:.4f}")
                continue
        if pnl > 0 and check_trailing_stop(symbol, pnl):
            res = close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close(symbol, current, pnl)
                if symbol in trailing_stops: del trailing_stops[symbol]
                consecutive_losses = 0
                send_telegram(f"📉 <b>TRAILING STOP</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nPnL: <b>+{pnl:.4f} USDT</b>")
                logger.info(f"Trailing stop {symbol} | PnL: {pnl:.4f}")

def handle_commands():
    global bot_running, force_trade, consecutive_losses
    logger.info("Telegram handler started")
    while bot_running:
        try:
            updates = get_telegram_updates()
            for u in updates:
                msg, chat_id, text = u.get("message", {}), str(u.get("message", {}).get("chat", {}).get("id", "")), u.get("message", {}).get("text", "").strip().lower()
                if chat_id != TELEGRAM_CHAT_ID: continue
                if text == "/status":
                    positions, balance, daily_pnl = get_positions(), get_balance(), get_today_pnl()
                    if not positions:
                        send_telegram(f"📊 <b>Status</b>\nBalance: <b>{balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nPositions: <b>0/{MAX_POSITIONS}</b>\nConsecutive losses: <b>{consecutive_losses}</b>")
                    else:
                        lines = [f"📊 <b>Status</b>\nBalance: <b>{balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nPositions: <b>{len(positions)}/{MAX_POSITIONS}</b>\nConsecutive losses: <b>{consecutive_losses}</b>\n"]
                        for p in positions:
                            pnl, entry, current = float(p.get("unrealizedPL", 0)), float(p.get("openPriceAvg", 0)), float(p.get("markPrice", 0))
                            emoji = "🟢" if pnl > 0 else "🔴"
                            pnl_pct = ((current - entry) / entry * 100) if p.get("holdSide") == "long" else ((entry - current) / entry * 100)
                            lines.append(f"{emoji} {p.get('holdSide','').upper()} {p['symbol']}\nEntry: {entry:.6f} | Now: {current:.6f}\nPnL: <b>{pnl:.4f} USDT ({pnl_pct:+.2f}%)</b>")
                        send_telegram("\n\n".join(lines))
                elif text == "/balance":
                    balance, daily_pnl = get_balance(), get_today_pnl()
                    send_telegram(f"💰 <b>Balance</b>\nAvailable: <b>{balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nMax daily loss: <b>{MAX_DAILY_LOSS_USD} USDT</b>")
                elif text == "/history":
                    summary = get_trade_summary()
                    if not summary:
                        send_telegram("📈 Belum ada trade history.")
                    else:
                        send_telegram(f"📈 <b>Trade History</b>\n\nTotal trades: <b>{summary['total_trades']}</b>\nWin rate: <b>{summary['win_rate']}</b>\nAvg PnL: <b>{summary['avg_pnl']} USDT</b>\nBest pair: <b>{summary['best_pair']}</b>\nWorst pair: <b>{summary['worst_pair']}</b>\n\n<b>Last 10 Trades:</b>\n{summary['last_10']}")
                elif text == "/trade":
                    force_trade = True
                    consecutive_losses = 0
                    send_telegram("⚡ Starting analysis...")
                elif text.startswith("/close"):
                    parts = text.split()
                    if len(parts) == 1:
                        send_telegram("⏳ Closing all positions...")
                        close_all_positions()
                    else:
                        sym = parts[1].upper()
                        positions = get_positions()
                        pos = next((p for p in positions if p["symbol"].upper() == sym), None)
                        if not pos:
                            send_telegram(f"⚠️ No position for {sym}")
                        else:
                            hold, pnl, price = pos.get("holdSide", "long"), float(pos.get("unrealizedPL", 0)), float(pos.get("markPrice", 0))
                            res = close_position_api(sym, hold)
                            if res.get("code") == "00000":
                                save_trade_close(sym, price, pnl)
                                if sym in trailing_stops: del trailing_stops[sym]
                                emoji = "✅" if pnl > 0 else "❌"
                                send_telegram(f"{emoji} <b>CLOSED</b> {hold.upper()} {sym}\nPnL: <b>{pnl:.4f} USDT</b>")
                            else:
                                send_telegram(f"⚠️ Failed to close {sym}: {res.get('msg')}")
                elif text == "/stop":
                    send_telegram("🛑 Bot stopped.")
                    bot_running = False
                elif text == "/help":
                    send_telegram(f"📋 <b>Commands</b>\n\n/status — positions + PnL\n/balance — balance + daily PnL\n/history — trade stats\n/trade — force trade now\n/close [SYMBOL] — close position(s)\n/stop — stop bot\n\n<b>Settings:</b>\nMax positions: {MAX_POSITIONS}\nStop loss: -{STOP_LOSS_PCT}%\nTake profit: ${TAKE_PROFIT_USD}\nMax daily loss: ${MAX_DAILY_LOSS_USD}")
            time.sleep(1)
        except Exception as e:
            logger.error(f"handle_commands error: {e}")
            time.sleep(1)

def main():
    global bot_running
    logger.info("=== Bitget LLM Bot V2 (Learning Edition) ===")
    send_telegram(f"🤖 <b>Bitget LLM Bot V2</b>\n🧠 <b>Learning Edition</b>\n\nMax positions: <b>{MAX_POSITIONS}</b>\nStop loss: <b>-{STOP_LOSS_PCT}%</b>\nTake profit: <b>${TAKE_PROFIT_USD}</b>\nTrailing stop: <b>{TRAILING_STOP_PCT}%</b>\nMax daily loss: <b>${MAX_DAILY_LOSS_USD}</b>\nMin confidence: <b>{MIN_CONFIDENCE}%</b>\n\nType /help for commands.")
    init_db()
    t = threading.Thread(target=handle_commands, daemon=True)
    t.start()
    while bot_running:
        try:
            positions, balance = get_positions(), get_balance()
            logger.info(f"Balance: {balance:.4f} | Positions: {len(positions)}/{MAX_POSITIONS}")
            if positions:
                for p in positions:
                    pnl = float(p.get("unrealizedPL", 0))
                    logger.info(f"Position: {p.get('holdSide','').upper()} {p['symbol']} | PnL: {pnl:.4f}")
                manage_positions()
            if len(positions) < MAX_POSITIONS: find_and_trade()
            if not force_trade:
                logger.info(f"Sleeping {SLEEP_MINUTES} min...")
                time.sleep(SLEEP_MINUTES * 60)
            else:
                time.sleep(5)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
            bot_running = False
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(60)
    send_telegram("🛑 Bot stopped.")
    logger.info("Bot stopped")

if __name__ == "__main__":
    main()
