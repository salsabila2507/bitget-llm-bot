import os, sys, subprocess, time, logging, json, requests, hmac, hashlib, base64, math, threading, sqlite3
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('/root/bitget-llm-bot/bitget_bot.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

def load_runtime_env(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                if not key or value == "":
                    continue
                os.environ.setdefault(key, value)
    except Exception as e:
        logger.error(f"Failed to load runtime env from {path}: {e}")

for env_path in (".env", ".runtime.env"):
    load_runtime_env(env_path)

def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

def env_int(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except Exception:
        return default

def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default

API_KEY = os.environ.get("BITGET_API_KEY", "")
SECRET_KEY = os.environ.get("BITGET_SECRET_KEY", "")
PASSPHRASE = os.environ.get("BITGET_PASSPHRASE", "")
BASE_URL = "https://api.bitget.com"
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
LLM_MODEL = os.environ.get("NVIDIA_LLM_MODEL", "meta/llama-3.3-70b-instruct")
LLM_FALLBACK_MODELS = [
    "meta/llama-3.3-70b-instruct",
    "openai/gpt-oss-120b",
    "mistralai/mistral-nemotron",
    "openai/gpt-oss-20b",
    "meta/llama-3.1-8b-instruct",
]
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = {c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", TELEGRAM_CHAT_ID).split(",") if c.strip()}
DRY_RUN = env_bool("DRY_RUN", env_bool("BITGET_DRY_RUN", True))
DRY_RUN_BALANCE = env_float("DRY_RUN_BALANCE", 5.0)
DRY_RUN_POLL_SECONDS = env_int("DRY_RUN_POLL_SECONDS", 15)
TRADE_MODE = os.environ.get("TRADE_MODE", os.environ.get("BITGET_TRADE_MODE", "scalping")).strip().lower()
TAKER_FEE_RATE = 0.0006
LLM_ERROR_COOLDOWN_SECONDS = 300
LLM_REQUEST_TIMEOUT_SECONDS = 30
RECENT_TRADE_LIMIT = 20
DIRECTION_MIN_TRADES = 5
DIRECTION_BLOCK_WIN_RATE = 55.0
DIRECTION_BLOCK_AVG_PNL = 0.0
DIRECTION_LOSS_STREAK_LIMIT = 3
DIRECTION_LOSS_STREAK_COOLDOWN_MIN = 60
PAIR_RECENT_TRADE_LIMIT = 10
PAIR_NEGATIVE_EV_THRESHOLD = 0.0
PAIR_NEGATIVE_EV_MIN_TRADES = 3
PAIR_DIRECTION_RECENT_TRADE_LIMIT = 8
PAIR_DIRECTION_NEGATIVE_EV_THRESHOLD = 0.0
PAIR_DIRECTION_MIN_TRADES = 2
PAIR_DIRECTION_BLOCK_WIN_RATE = 50.0
PAIR_LOSS_STREAK_LIMIT = 2
PAIR_LOSS_STREAK_COOLDOWN_HOURS = 12
MIN_QUOTE_VOLUME_USDT = 500000.0
AUTO_OPEN_ON_LLM_FALLBACK = False
SIGNAL_NOTIF_COOLDOWN_MIN = 60
STALE_OPEN_TRADE_HOURS = 24
MAX_HOLD_HOURS = 6
CONSECUTIVE_LOSS_COOLDOWN_MIN = 60
BLACKLIST_MIN_TRADES = 5
BLACKLIST_LOSS_RATE_PCT = 70.0
BLACKLIST_AVG_PNL_THRESHOLD = -0.02

MIN_NOTIONAL = 5.5
MIN_LEVERAGE, MAX_LEVERAGE = 1, 125
RISK_MAX_LEVERAGE = 5
LOW_CONFIDENCE_MAX_LEVERAGE = 4
MID_CONFIDENCE_MAX_LEVERAGE = 4
MAX_MARGIN_PER_TRADE_FRACTION = 0.30
MIN_FREE_BALANCE_USDT = 0.20
MIN_LIQUIDATION_BUFFER_PCT = 5.0
MARGIN_MODE, PRODUCT_TYPE, MARGIN_COIN = "isolated", "USDT-FUTURES", "USDT"
SLEEP_MINUTES = 5 if TRADE_MODE == "scalping" else 60

MAX_POSITIONS = max(1, env_int("MAX_POSITIONS", env_int("MAX_PAIRS", 2)))
MAX_ORDERS_PER_CYCLE = max(1, min(MAX_POSITIONS, env_int("MAX_ORDERS_PER_CYCLE", 1)))
TAKE_PROFIT_ROI_PCT, STOP_LOSS_ROI_PCT = (10.0, 6.0) if TRADE_MODE == "scalping" else (70.0, 40.0)
MAX_DAILY_LOSS_USD, TRADE_COOLDOWN_MIN = 0.75, 10
TRAILING_STOP_PCT, MIN_CONFIDENCE = (2.0, 80) if TRADE_MODE == "scalping" else (3.0, 70)
TRAILING_ACTIVATE_ROI_PCT = 8.0 if TRADE_MODE == "scalping" else 20.0
MIN_TRAILING_PROFIT_ROI_PCT = 5.0 if TRADE_MODE == "scalping" else 10.0
CONSECUTIVE_LOSS_LIMIT = 3
TIMEFRAMES = ["15m", "1H", "4H"]
SIGNAL_SCAN_COUNT, TOP_SIGNAL_COUNT = 50, 10
DB_PATH = "/root/trade_history.db"

bot_running, force_trade, last_update_id = True, False, 0
last_trade_time, daily_pnl = 0, 0.0
trailing_stops, consecutive_losses, blacklisted_pairs = {}, 0, set()
llm_cooldown_until, daily_loss_locked_date = 0, None
consecutive_loss_cooldown_until = 0
llm_disabled_models = set()
direction_cooldowns = {"LONG": 0, "SHORT": 0}
direction_cooldown_loss_streak_snapshot = {"LONG": [], "SHORT": []}
last_signal_notif_time = 0
last_signal_notif_state = None

TRADE_PROFILES = {
    "normal": {
        "sleep_minutes": 60,
        "take_profit_roi_pct": 70.0,
        "stop_loss_roi_pct": 40.0,
        "trailing_stop_pct": 3.0,
        "trailing_activate_roi_pct": 20.0,
        "min_trailing_profit_roi_pct": 10.0,
        "min_confidence": 70,
    },
    "scalping": {
        "sleep_minutes": 5,
        "take_profit_roi_pct": 10.0,
        "stop_loss_roi_pct": 6.0,
        "trailing_stop_pct": 2.0,
        "trailing_activate_roi_pct": 8.0,
        "min_trailing_profit_roi_pct": 5.0,
        "min_confidence": 80,
    },
}

def apply_trade_mode(mode):
    global TRADE_MODE, SLEEP_MINUTES, TAKE_PROFIT_ROI_PCT, STOP_LOSS_ROI_PCT, TRAILING_STOP_PCT, MIN_CONFIDENCE, TRAILING_ACTIVATE_ROI_PCT, MIN_TRAILING_PROFIT_ROI_PCT
    mode = str(mode).strip().lower()
    if mode not in TRADE_PROFILES:
        return False
    TRADE_MODE = mode
    profile = TRADE_PROFILES[mode]
    SLEEP_MINUTES = profile["sleep_minutes"]
    TAKE_PROFIT_ROI_PCT = profile["take_profit_roi_pct"]
    STOP_LOSS_ROI_PCT = profile["stop_loss_roi_pct"]
    TRAILING_STOP_PCT = profile["trailing_stop_pct"]
    TRAILING_ACTIVATE_ROI_PCT = profile["trailing_activate_roi_pct"]
    MIN_TRAILING_PROFIT_ROI_PCT = profile["min_trailing_profit_roi_pct"]
    MIN_CONFIDENCE = profile["min_confidence"]
    return True

if not apply_trade_mode(TRADE_MODE):
    logger.warning(f"Unknown TRADE_MODE={TRADE_MODE}; falling back to scalping")
    apply_trade_mode("scalping")

def ensure_daemonized():
    if os.environ.get("BITGET_BOT_DAEMON") == "1":
        return
    env = os.environ.copy()
    env["BITGET_BOT_DAEMON"] = "1"
    script_path = os.path.abspath(__file__)
    subprocess.Popen(
        [sys.executable, "-u", script_path],
        env=env,
        cwd=os.path.dirname(script_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    sys.exit(0)

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

def hold_side_to_direction(hold_side):
    return "LONG" if str(hold_side).lower() == "long" else "SHORT"

def save_trade_close(symbol, exit_price, pnl, hold_side=None):
    conn = sqlite3.connect(DB_PATH)
    closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if hold_side:
        direction = hold_side_to_direction(hold_side)
        cur = conn.execute("""SELECT id FROM trades
            WHERE symbol=? AND closed_at IS NULL AND UPPER(action) LIKE ?
            ORDER BY id DESC LIMIT 1""", (symbol, f"%{direction}%"))
        row = cur.fetchone()
        if row:
            conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=? WHERE id=?",
                (exit_price, pnl, closed_at, row[0]))
        else:
            conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=? WHERE symbol=? AND closed_at IS NULL",
                (exit_price, pnl, closed_at, symbol))
    else:
        conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=? WHERE symbol=? AND closed_at IS NULL",
            (exit_price, pnl, closed_at, symbol))
    conn.commit()
    conn.close()

def save_trade_close_by_id(trade_id, exit_price, pnl, action=None):
    conn = sqlite3.connect(DB_PATH)
    if action is None:
        conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=? WHERE id=?",
            (exit_price, pnl, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), trade_id))
    else:
        conn.execute("UPDATE trades SET exit_price=?, pnl=?, closed_at=?, action=? WHERE id=?",
            (exit_price, pnl, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), action, trade_id))
    conn.commit()
    conn.close()

def cleanup_stale_dry_run_positions():
    if not DRY_RUN:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""SELECT id, symbol, action, entry_price, size, leverage, confidence, opened_at
            FROM trades
            WHERE closed_at IS NULL
              AND action IN ('LONG', 'SHORT', 'DRY_LONG', 'DRY_SHORT', 'DRY_MANUAL_LONG', 'DRY_MANUAL_SHORT')""")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return
        tickers = {t.get("symbol"): t for t in get_tickers()}
        now = datetime.now()
        closed = 0
        for trade_id, symbol, action, entry_price, size, leverage, confidence, opened_at in rows:
            try:
                opened_dt = datetime.strptime(opened_at, "%Y-%m-%d %H:%M:%S")
            except Exception:
                opened_dt = now
            age_hours = (now - opened_dt).total_seconds() / 3600
            if age_hours < STALE_OPEN_TRADE_HOURS:
                continue
            hold_side = direction_from_action(action)
            current = parse_float(tickers.get(symbol, {}).get("lastPr"), parse_float(entry_price, 0.0))
            position = {
                "symbol": symbol,
                "action": action,
                "openPriceAvg": entry_price,
                "size": size,
                "leverage": leverage,
                "confidence": confidence,
                "holdSide": hold_side,
            }
            pnl, fee, size, current, entry = estimate_position_net_pnl(position, current)
            stale_action = action if str(action).upper().startswith("STALE_") else f"STALE_{action}"
            save_trade_close_by_id(trade_id, current, pnl, action=stale_action)
            closed += 1
            logger.info(f"Closed stale dry-run {hold_side.upper()} {symbol} id={trade_id} | Net PnL: {pnl:.4f} | Tagged {stale_action}")
        if closed:
            send_telegram(f"🧹 <b>Dry-run cleanup</b>\nClosed stale open paper trades: <b>{closed}</b>")
    except Exception as e:
        logger.error(f"cleanup_stale_dry_run_positions error: {e}")

def is_manual_action(action):
    return "MANUAL" in str(action).upper()

def direction_from_action(action):
    action = str(action).upper()
    return "long" if "LONG" in action else "short"

def action_direction(action):
    action = str(action).upper()
    if "LONG" in action:
        return "LONG"
    if "SHORT" in action:
        return "SHORT"
    return None

def position_state_key(symbol, hold_side):
    return f"{symbol}:{str(hold_side).lower()}"

def clear_trailing_stop(symbol, hold_side):
    trailing_stops.pop(position_state_key(symbol, hold_side), None)
    trailing_stops.pop(symbol, None)

def get_dry_run_positions():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""SELECT id, symbol, action, entry_price, size, leverage, confidence, opened_at
            FROM trades WHERE closed_at IS NULL AND action IN ('DRY_LONG', 'DRY_SHORT', 'DRY_MANUAL_LONG', 'DRY_MANUAL_SHORT')""")
        rows = cur.fetchall()
        conn.close()
        return [{"id": r[0], "symbol": r[1], "action": r[2], "openPriceAvg": r[3],
                 "size": r[4], "leverage": r[5], "confidence": r[6], "opened_at": r[7],
                 "holdSide": direction_from_action(r[2])} for r in rows]
    except:
        return []

def get_open_trade_opened_at(symbol, hold_side):
    """Look up opened_at for a still-open trade by symbol + side (LIVE path)."""
    try:
        direction = str(hold_side).upper()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""SELECT opened_at FROM trades
            WHERE symbol=? AND closed_at IS NULL AND UPPER(action) LIKE ?
            ORDER BY id DESC LIMIT 1""", (symbol, f"%{direction}%"))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None

def position_age_hours(position):
    opened_at = position.get("opened_at")
    if not opened_at and not DRY_RUN:
        opened_at = get_open_trade_opened_at(position.get("symbol", ""), position.get("holdSide", "long"))
    if not opened_at:
        return 0.0
    try:
        opened_dt = datetime.strptime(opened_at, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return 0.0
    return (datetime.now() - opened_dt).total_seconds() / 3600

def get_strategy_positions():
    return get_dry_run_positions() if DRY_RUN else get_positions()

def get_open_manual_position_keys():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("""SELECT symbol, action FROM trades
            WHERE closed_at IS NULL AND action IN ('DRY_MANUAL_LONG', 'DRY_MANUAL_SHORT', 'MANUAL_LONG', 'MANUAL_SHORT')""")
        rows = cur.fetchall()
        conn.close()
        return {(symbol, direction_from_action(action)) for symbol, action in rows}
    except:
        return set()

def get_auto_strategy_positions():
    positions = get_strategy_positions()
    if DRY_RUN:
        return [p for p in positions if not is_manual_action(p.get("action", ""))]
    manual_keys = get_open_manual_position_keys()
    return [p for p in positions if (p.get("symbol"), p.get("holdSide", "long")) not in manual_keys]

def get_position_counts():
    all_positions = get_strategy_positions()
    auto_positions = get_auto_strategy_positions()
    manual_count = max(0, len(all_positions) - len(auto_positions))
    return all_positions, auto_positions, manual_count

def get_strategy_balance():
    return DRY_RUN_BALANCE if DRY_RUN else get_balance()

def get_trade_summary():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT * FROM trades WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%' ORDER BY closed_at DESC")
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
        max_age_days = STALE_OPEN_TRADE_HOURS / 24.0
        cur = conn.execute("""SELECT SUM(pnl) FROM trades
            WHERE closed_at LIKE ?
              AND pnl IS NOT NULL
              AND action NOT LIKE 'STALE_%'
              AND (opened_at LIKE ? OR julianday(closed_at) - julianday(opened_at) <= ?)""",
            (f"{today}%", f"{today}%", max_age_days))
        result = cur.fetchone()[0]
        conn.close()
        return result if result else 0.0
    except: return 0.0

def get_open_dry_run_net_pnl():
    if not DRY_RUN:
        return 0.0
    try:
        tickers = {t.get("symbol"): t for t in get_tickers()}
        total = 0.0
        for p in get_dry_run_positions():
            entry = float(p.get("openPriceAvg", 0))
            ticker = tickers.get(p["symbol"], {})
            current = parse_float(ticker.get("lastPr"), entry)
            net_pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
            total += net_pnl
        return total
    except:
        return 0.0

def get_strategy_today_net_pnl():
    pnl = get_today_pnl()
    if DRY_RUN:
        pnl += get_open_dry_run_net_pnl()
    return pnl

def estimate_round_trip_fee(entry_price, exit_price, size):
    entry_notional = abs(entry_price * size)
    exit_notional = abs(exit_price * size)
    return (entry_notional + exit_notional) * TAKER_FEE_RATE

def calculate_net_pnl(entry_price, exit_price, size, hold_side):
    gross = (exit_price - entry_price) * size if hold_side == "long" else (entry_price - exit_price) * size
    fee = estimate_round_trip_fee(entry_price, exit_price, size)
    return gross - fee, fee

def get_pair_performance(symbol):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT COUNT(*), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), AVG(pnl) FROM trades WHERE symbol=? AND closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'", (symbol,))
        row = cur.fetchone()
        conn.close()
        if not row or row[0] == 0: return None
        total_trades, wins, avg_pnl = row[0], row[1], row[2]
        win_rate = (wins / total_trades) * 100
        return {"total": total_trades, "win_rate": win_rate, "avg_pnl": avg_pnl}
    except: return None

def get_direction_performance():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT action, pnl FROM trades WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%' ORDER BY closed_at DESC LIMIT 100")
        rows = cur.fetchall()
        conn.close()
        stats = {"LONG": {"total": 0, "wins": 0, "pnl": 0.0}, "SHORT": {"total": 0, "wins": 0, "pnl": 0.0}}
        for action, pnl in rows:
            direction = action_direction(action)
            if direction not in stats:
                continue
            pnl = parse_float(pnl, 0.0)
            stats[direction]["total"] += 1
            stats[direction]["pnl"] += pnl
            if pnl > 0:
                stats[direction]["wins"] += 1
        for direction in stats:
            total = stats[direction]["total"]
            stats[direction]["win_rate"] = (stats[direction]["wins"] / total * 100) if total else 0.0
            stats[direction]["avg_pnl"] = (stats[direction]["pnl"] / total) if total else 0.0
        return stats
    except:
        return {"LONG": {"total": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0, "avg_pnl": 0.0},
                "SHORT": {"total": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0, "avg_pnl": 0.0}}

def get_recent_direction_performance(limit=RECENT_TRADE_LIMIT):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT action, pnl FROM trades WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%' ORDER BY closed_at DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        conn.close()
        stats = {"LONG": {"total": 0, "wins": 0, "pnl": 0.0}, "SHORT": {"total": 0, "wins": 0, "pnl": 0.0}}
        for action, pnl in rows:
            direction = action_direction(action)
            if direction not in stats:
                continue
            pnl = parse_float(pnl, 0.0)
            stats[direction]["total"] += 1
            stats[direction]["pnl"] += pnl
            if pnl > 0:
                stats[direction]["wins"] += 1
        for direction in stats:
            total = stats[direction]["total"]
            stats[direction]["win_rate"] = (stats[direction]["wins"] / total * 100) if total else 0.0
            stats[direction]["avg_pnl"] = (stats[direction]["pnl"] / total) if total else 0.0
        return stats
    except:
        return {"LONG": {"total": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0, "avg_pnl": 0.0},
                "SHORT": {"total": 0, "wins": 0, "pnl": 0.0, "win_rate": 0.0, "avg_pnl": 0.0}}

def direction_allowed(direction):
    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return False
    if time.time() < direction_cooldowns.get(direction, 0):
        return False
    stats = get_recent_direction_performance()
    d = stats[direction]
    if d["total"] < DIRECTION_MIN_TRADES:
        return True
    # Block when recent data is decisively bad: poor win rate AND non-positive
    # average net PnL. (Avg PnL >= 0 means we're not bleeding even at low WR.)
    if d["win_rate"] < DIRECTION_BLOCK_WIN_RATE and d["avg_pnl"] <= DIRECTION_BLOCK_AVG_PNL:
        return False
    return True

def evaluate_direction_loss_streak(direction):
    """If the last N closed trades on this side are all losses, return cooldown reason."""
    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            """SELECT pnl FROM trades
               WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'
                 AND UPPER(action) LIKE ?
               ORDER BY closed_at DESC LIMIT ?""",
            (f"%{direction}%", DIRECTION_LOSS_STREAK_LIMIT))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return None
    if len(rows) < DIRECTION_LOSS_STREAK_LIMIT:
        return None
    if all(r[0] is not None and r[0] < 0 for r in rows):
        return f"last {DIRECTION_LOSS_STREAK_LIMIT} {direction} trades all losses"
    return None

def check_and_apply_loss_streak_cooldowns():
    """Refresh direction_cooldowns based on the latest closed trades.

    Only apply cooldown once per unique loss streak. Track the loss streak
    snapshot to avoid re-applying cooldown for the same streak after it expires.
    """
    now = time.time()
    for direction in ("LONG", "SHORT"):
        if now < direction_cooldowns.get(direction, 0):
            continue  # already cooling

        # Get current loss streak
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.execute(
                """SELECT pnl FROM trades
                   WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'
                     AND UPPER(action) LIKE ?
                   ORDER BY closed_at DESC LIMIT ?""",
                (f"%{direction}%", DIRECTION_LOSS_STREAK_LIMIT))
            current_streak = [r[0] for r in cur.fetchall()]
            conn.close()
        except Exception:
            current_streak = []

        # Check if this is the same loss streak we already cooled down for
        if current_streak == direction_cooldown_loss_streak_snapshot.get(direction, []):
            continue  # same streak, don't re-apply cooldown

        # Evaluate if current streak warrants cooldown
        reason = evaluate_direction_loss_streak(direction)
        if reason:
            # New loss streak detected - apply cooldown and save snapshot
            direction_cooldowns[direction] = now + DIRECTION_LOSS_STREAK_COOLDOWN_MIN * 60
            direction_cooldown_loss_streak_snapshot[direction] = current_streak
            logger.warning(f"{direction} cooldown: {reason}; pausing {DIRECTION_LOSS_STREAK_COOLDOWN_MIN} min")
            send_telegram(f"⏸️ <b>{direction} cooldown</b>\nReason: {reason}\nPaused for {DIRECTION_LOSS_STREAK_COOLDOWN_MIN} min")
        else:
            # No loss streak - clear the snapshot so future streaks can trigger
            direction_cooldown_loss_streak_snapshot[direction] = []

def get_pair_recent_stats(symbol, limit=PAIR_RECENT_TRADE_LIMIT):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            """SELECT pnl FROM trades
               WHERE symbol=? AND closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'
               ORDER BY closed_at DESC LIMIT ?""", (symbol, limit))
        rows = [r[0] for r in cur.fetchall() if r[0] is not None]
        conn.close()
    except Exception:
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    total = len(rows)
    if total == 0:
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    wins = sum(1 for p in rows if p > 0)
    return {
        "total": total,
        "wins": wins,
        "win_rate": wins / total * 100,
        "avg_pnl": sum(rows) / total,
    }

def pair_loss_streak_active(symbol):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            """SELECT pnl, closed_at FROM trades
               WHERE symbol=? AND closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'
               ORDER BY closed_at DESC LIMIT ?""",
            (symbol, PAIR_LOSS_STREAK_LIMIT))
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return False, ""
    if len(rows) < PAIR_LOSS_STREAK_LIMIT:
        return False, ""
    if not all(r[0] is not None and r[0] < 0 for r in rows):
        return False, ""
    try:
        last_closed = datetime.strptime(rows[0][1], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return True, f"last {PAIR_LOSS_STREAK_LIMIT} trades were losses"
    age_hours = (datetime.now() - last_closed).total_seconds() / 3600
    if age_hours <= PAIR_LOSS_STREAK_COOLDOWN_HOURS:
        return True, f"last {PAIR_LOSS_STREAK_LIMIT} trades were losses; cooling {PAIR_LOSS_STREAK_COOLDOWN_HOURS}h"
    return False, ""

def pair_negative_ev(symbol):
    s = get_pair_recent_stats(symbol)
    if s["total"] < PAIR_NEGATIVE_EV_MIN_TRADES:
        return False, s
    return s["avg_pnl"] < PAIR_NEGATIVE_EV_THRESHOLD, s

def get_pair_direction_recent_stats(symbol, direction, limit=PAIR_DIRECTION_RECENT_TRADE_LIMIT):
    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            """SELECT pnl FROM trades
               WHERE symbol=? AND closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'
                 AND UPPER(action) LIKE ?
               ORDER BY closed_at DESC LIMIT ?""",
            (symbol, f"%{direction}%", limit))
        rows = [r[0] for r in cur.fetchall() if r[0] is not None]
        conn.close()
    except Exception:
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    total = len(rows)
    if total == 0:
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    wins = sum(1 for p in rows if p > 0)
    return {
        "total": total,
        "wins": wins,
        "win_rate": wins / total * 100,
        "avg_pnl": sum(rows) / total,
    }

def pair_direction_negative_ev(symbol, direction):
    s = get_pair_direction_recent_stats(symbol, direction)
    if s["total"] < PAIR_DIRECTION_MIN_TRADES:
        return False, s
    is_bad = (
        s["avg_pnl"] <= PAIR_DIRECTION_NEGATIVE_EV_THRESHOLD
        and s["win_rate"] < PAIR_DIRECTION_BLOCK_WIN_RATE
    )
    return is_bad, s

def get_learning_context():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT symbol, action, pnl, confidence FROM trades WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%' ORDER BY closed_at DESC LIMIT 20")
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
        direction_stats = get_direction_performance()
        recent_direction_stats = get_recent_direction_performance()
        context += "\nDirectional performance (all tracked):\n"
        for direction in ("LONG", "SHORT"):
            d = direction_stats[direction]
            context += f"- {direction}: Win rate {d['win_rate']:.1f}% | Avg PnL: {d['avg_pnl']:.4f} USDT | Trades: {d['total']}\n"
        context += f"\nRecent directional performance (last {RECENT_TRADE_LIMIT} closed trades):\n"
        for direction in ("LONG", "SHORT"):
            d = recent_direction_stats[direction]
            context += f"- {direction}: Win rate {d['win_rate']:.1f}% | Avg PnL: {d['avg_pnl']:.4f} USDT | Trades: {d['total']}\n"
        pair_side_stats = defaultdict(lambda: {"total": 0, "wins": 0, "pnl": 0.0})
        for symbol, action, pnl, conf in rows:
            direction = action_direction(action)
            if not direction or pnl is None:
                continue
            key = (symbol, direction)
            pnl = parse_float(pnl, 0.0)
            pair_side_stats[key]["total"] += 1
            pair_side_stats[key]["pnl"] += pnl
            if pnl > 0:
                pair_side_stats[key]["wins"] += 1
        pair_side_rows = []
        for (symbol, direction), s in pair_side_stats.items():
            if s["total"] < PAIR_DIRECTION_MIN_TRADES:
                continue
            s["win_rate"] = s["wins"] / s["total"] * 100
            s["avg_pnl"] = s["pnl"] / s["total"]
            pair_side_rows.append((symbol, direction, s))
        if pair_side_rows:
            context += "\nRecent pair+direction performance:\n"
            best_side = sorted(pair_side_rows, key=lambda x: x[2]["avg_pnl"], reverse=True)[:3]
            worst_side = sorted(pair_side_rows, key=lambda x: x[2]["avg_pnl"])[:3]
            context += "- Best side setups: " + ", ".join(
                [f"{symbol} {direction} avg {s['avg_pnl']:+.4f} USDT WR {s['win_rate']:.0f}% ({s['total']}x)" for symbol, direction, s in best_side]
            ) + "\n"
            context += "- Weak side setups: " + ", ".join(
                [f"{symbol} {direction} avg {s['avg_pnl']:+.4f} USDT WR {s['win_rate']:.0f}% ({s['total']}x)" for symbol, direction, s in worst_side]
            ) + "\n"
        blocked = [d for d in ("LONG", "SHORT") if not direction_allowed(d)]
        if blocked:
            context += f"\nCurrently blocked directions (recent win rate < {DIRECTION_BLOCK_WIN_RATE:.0f}% AND avg PnL <= {DIRECTION_BLOCK_AVG_PNL:.2f}, OR active loss-streak cooldown): {', '.join(blocked)}\n"
        else:
            context += "\nBoth LONG and SHORT are allowed; pick the side that price action and momentum support.\n"
        now = time.time()
        for direction in ("LONG", "SHORT"):
            cd = direction_cooldowns.get(direction, 0)
            if cd > now:
                mins = int((cd - now) / 60) + 1
                context += f"- {direction} on loss-streak cooldown for ~{mins} more min — do NOT pick this side.\n"
        context += "\nDecision rules:\n"
        context += f"- Avoid pairs whose recent avg net PnL < {PAIR_NEGATIVE_EV_THRESHOLD:.3f} USDT over >= {PAIR_NEGATIVE_EV_MIN_TRADES} trades. Round-trip taker fee is ~0.0072 USDT per scalping trade, so anything close to zero net PnL is a fee-eating churn.\n"
        context += f"- Avoid a specific pair+direction after >= {PAIR_DIRECTION_MIN_TRADES} trades when its avg net PnL <= {PAIR_DIRECTION_NEGATIVE_EV_THRESHOLD:.3f} USDT and win rate < {PAIR_DIRECTION_BLOCK_WIN_RATE:.0f}%.\n"
        context += "- Prefer pairs with clearly positive recent avg net PnL on the side you propose.\n"
        context += "- If neither side has edge in this candidate, set open:false rather than forcing a trade.\n"
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
        cur = conn.execute("""SELECT symbol, COUNT(*) as total, SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses, AVG(pnl) as avg_pnl
            FROM trades WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%' GROUP BY symbol HAVING total >= ?""",
            (BLACKLIST_MIN_TRADES,))
        rows = cur.fetchall()
        conn.close()
        new_blacklist = set()
        for row in rows:
            symbol, total, losses, avg_pnl = row
            loss_rate = (losses / total) * 100
            if loss_rate >= BLACKLIST_LOSS_RATE_PCT or parse_float(avg_pnl, 0.0) <= BLACKLIST_AVG_PNL_THRESHOLD:
                new_blacklist.add(symbol)
        added = new_blacklist - blacklisted_pairs
        removed = blacklisted_pairs - new_blacklist
        for symbol in added:
            logger.warning(f"Blacklisted {symbol} (loss rate >= {BLACKLIST_LOSS_RATE_PCT:.0f}% or avg PnL <= {BLACKLIST_AVG_PNL_THRESHOLD:+.3f})")
        for symbol in removed:
            logger.info(f"Removed {symbol} from blacklist (loss rate improved)")
        blacklisted_pairs = new_blacklist
    except Exception as e:
        logger.error(f"update_blacklist error: {e}")

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
    if res.get("code") != "00000":
        logger.error(f"Bitget balance API response: {json.dumps(res, ensure_ascii=False)}")
        return 0.0
    accs = res.get("data", [])
    if isinstance(accs, dict):
        accs = [accs]
    for a in accs:
        if not isinstance(a, dict):
            continue
        if str(a.get("marginCoin", "")).upper() != MARGIN_COIN:
            continue
        for key in ("available", "isolatedMaxAvailable", "crossedMaxAvailable", "maxTransferOut", "usdtEquity", "accountEquity", "unionAvailable"):
            balance = parse_float(a.get(key), 0.0)
            if balance > 0:
                return balance
        for asset in a.get("assetList", []):
            if not isinstance(asset, dict):
                continue
            if str(asset.get("coin", "")).upper() != MARGIN_COIN:
                continue
            for key in ("available", "balance"):
                balance = parse_float(asset.get(key), 0.0)
                if balance > 0:
                    return balance
    logger.error(f"Bitget balance API response: {json.dumps(res, ensure_ascii=False)}")
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

def place_order(symbol, side, size, hold_side="long", tp_price=None, sl_price=None):
    body = {"symbol": symbol, "productType": PRODUCT_TYPE, "marginMode": MARGIN_MODE, "marginCoin": MARGIN_COIN,
            "size": str(size), "side": side, "tradeSide": "open", "orderType": "market", "holdSide": hold_side}
    if tp_price:
        body["presetStopSurplusPrice"] = str(tp_price)
    if sl_price:
        body["presetStopLossPrice"] = str(sl_price)
    return api_post("/api/v2/mix/order/place-order", body)

def close_position_api(symbol, hold_side="long"):
    body = {"symbol": symbol, "productType": PRODUCT_TYPE, "holdSide": hold_side}
    return api_post("/api/v2/mix/order/close-positions", body)

def close_all_positions():
    positions = get_strategy_positions() if DRY_RUN else get_positions()
    for p in positions:
        symbol, hold = p["symbol"], p.get("holdSide", "long")
        price = float(p.get("markPrice", p.get("openPriceAvg", 0)))
        pnl, fee, size, current, entry = estimate_position_net_pnl(p, price)
        if DRY_RUN:
            res = {"code": "00000"}
        else:
            res = close_position_api(symbol, hold)
        if res.get("code") == "00000":
            save_trade_close_by_id(p["id"], price, pnl) if DRY_RUN else save_trade_close(symbol, price, pnl, hold)
            emoji = "✅" if pnl > 0 else "❌"
            prefix = "DRY RUN " if DRY_RUN else ""
            send_telegram(f"{emoji} <b>{prefix}CLOSED</b> {hold.upper()} {symbol}\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
            logger.info(f"{prefix}Closed {hold} {symbol} | Net PnL: {pnl:.4f} | Fee: {fee:.4f}")

def send_telegram(msg):
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
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
    global llm_cooldown_until, LLM_MODEL
    if time.time() < llm_cooldown_until:
        logger.warning("LLM cooldown active; skipping this analysis cycle")
        return None
    models = []
    for model in [LLM_MODEL] + LLM_FALLBACK_MODELS:
        if model in models or model in llm_disabled_models:
            continue
        models.append(model)
    if not models:
        logger.error("All LLM models marked unavailable; using fallback ranker")
        return None
    network_failures = 0
    for model in models:
        try:
            r = requests.post(f"{NVIDIA_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {NVIDIA_API_KEY}"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 1800}, timeout=LLM_REQUEST_TIMEOUT_SECONDS)
            status = r.status_code
            try:
                data = r.json()
            except Exception:
                data = None
            if data and "choices" in data and data["choices"]:
                content = (data["choices"][0].get("message") or {}).get("content")
                if content:
                    if model != LLM_MODEL:
                        logger.info(f"LLM fallback working: {model}")
                        LLM_MODEL = model
                    return content.strip()
                logger.warning(f"LLM {model} returned empty content; trying next")
                continue
            logger.error(f"LLM error on {model}: HTTP {status} body: {r.text[:300]}")
            # 404 = model not in this account -> disable for the rest of the session
            if status == 404:
                llm_disabled_models.add(model)
                logger.warning(f"Disabling {model} for this session (HTTP 404)")
            elif status == 429 or status >= 500:
                network_failures += 1
            continue
        except requests.exceptions.Timeout:
            logger.error(f"LLM timeout on {model}")
            network_failures += 1
            continue
        except Exception as e:
            logger.error(f"LLM error on {model}: {e}")
            network_failures += 1
            continue
    # Only enter cooldown when network/server is the problem, not when every
    # model returns 4xx (which would just be config error).
    if network_failures >= len(models):
        llm_cooldown_until = time.time() + LLM_ERROR_COOLDOWN_SECONDS
    return None

def parse_float(value, default=0.0):
    try:
        cleaned = str(value).replace("$", "").replace(",", "").replace("%", "").replace("x", "").replace("X", "")
        cleaned = cleaned.replace("USDT", "").replace("usdt", "").strip()
        return float(cleaned)
    except:
        return default

def parse_int(value, default=0):
    try:
        return int(float(str(value).replace("x", "").replace("X", "").strip()))
    except:
        return default

def parse_bool(value):
    if isinstance(value, bool): return value
    return str(value).strip().lower() in ["true", "yes", "1", "open"]

def ticker_quote_volume(ticker, price=0.0):
    for key in ("quoteVolume", "usdtVolume", "quoteVol", "quoteVolume24h", "turnover24h"):
        volume = parse_float(ticker.get(key), 0.0)
        if volume > 0:
            return volume
    return parse_float(ticker.get("baseVolume"), 0.0) * parse_float(price, 0.0)

def analyze_top_signals_fallback(tickers, balance):
    signals = []
    for rank, t in enumerate(tickers[:TOP_SIGNAL_COUNT], start=1):
        symbol = t.get("symbol")
        price = parse_float(t.get("lastPr"), 0.0)
        chg_pct = parse_float(t.get("changeUtc24h", t.get("priceChangePercent", t.get("change24h", 0.0))), 0.0)
        if not symbol or price <= 0:
            continue
        # Momentum-following fallback: ride the 24h move direction so we can
        # learn from both sides. The direction_allowed gate downstream will
        # still skip a side that recent data shows is decisively losing.
        direction = "LONG" if chg_pct >= 0 else "SHORT"
        confidence = MIN_CONFIDENCE + 2 if rank <= MAX_ORDERS_PER_CYCLE else max(50, MIN_CONFIDENCE - rank)
        leverage = LOW_CONFIDENCE_MAX_LEVERAGE
        margin = min(balance * MAX_MARGIN_PER_TRADE_FRACTION, max(0.0, balance - MIN_FREE_BALANCE_USDT))
        margin = max(0.0, margin)
        size = normalize_order_size((margin * leverage) / price) if margin > 0 else 0.0
        signals.append({
            "rank": rank,
            "symbol": symbol,
            "direction": direction,
            "confidence": confidence,
            "leverage": leverage,
            "margin_usdt": margin,
            "size": size,
            "possible": margin > 0 and size * price >= MIN_NOTIONAL,
            "open": AUTO_OPEN_ON_LLM_FALLBACK and rank <= MAX_ORDERS_PER_CYCLE and confidence >= MIN_CONFIDENCE,
            "reason": "Fallback watch-only momentum signal because NVIDIA LLM did not return a usable response.",
            "price": price,
        })
    return signals

def analyze_top_signals(tickers, balance):
    market_rows = []
    ticker_map = {}
    for t in tickers[:SIGNAL_SCAN_COUNT]:
        symbol = t.get("symbol")
        price = parse_float(t.get("lastPr"))
        volume = ticker_quote_volume(t, price)
        if not symbol or price <= 0: continue
        if volume < MIN_QUOTE_VOLUME_USDT: continue
        ticker_map[symbol] = t
        ps = get_pair_recent_stats(symbol)
        if ps["total"] >= 1:
            history_tag = f" | pair_hist({ps['total']}): WR {ps['win_rate']:.0f}%, avg {ps['avg_pnl']:+.4f} USDT"
        else:
            history_tag = " | pair_hist(0): no prior trades"
        side_tags = []
        for direction in ("LONG", "SHORT"):
            ds = get_pair_direction_recent_stats(symbol, direction)
            if ds["total"] >= 1:
                side_tags.append(f"{direction}({ds['total']}): WR {ds['win_rate']:.0f}%, avg {ds['avg_pnl']:+.4f}")
        if side_tags:
            history_tag += " | side_hist " + " / ".join(side_tags)
        market_rows.append(f"{symbol} | price={price} | volume_usdt={volume:.0f}{history_tag}")
    if not market_rows: return []
    style_hint = "scalping" if TRADE_MODE == "scalping" else "normal trading"
    learning_context = get_learning_context()
    prompt = f"""You are controlling a Bitget USDT futures bot with about ${balance:.4f} available balance.

Rank these {len(market_rows)} tickers and select the best {TOP_SIGNAL_COUNT} signals.
From those {TOP_SIGNAL_COUNT}, choose at most {MAX_ORDERS_PER_CYCLE} that is worth opening now.
This bot is running in {style_hint} mode.

=== LEARNING CONTEXT ===
{learning_context}

=== TICKERS (with recent per-pair history) ===
{chr(10).join(market_rows)}

Rules:
1. Return exactly {TOP_SIGNAL_COUNT} ranked signals.
2. Confidence must be 0-100.
3. OPEN can only be YES when confidence is at least {MIN_CONFIDENCE}.
4. You decide pair, LONG/SHORT, leverage, margin USDT, position size in base coin, and if the pair is possible with ${balance:.4f}.
5. Use the lowest leverage that can meet Bitget minimum notional about {MIN_NOTIONAL} USDT. Avoid high leverage; unsafe setups above {RISK_MAX_LEVERAGE}x will be rejected.
6. In scalping mode prefer fast momentum, tight structure, and cleaner entries over large trend ideas.
7. Use the learning context to compare LONG and SHORT performance separately. Pick the side that current price action, momentum, and recent results support — neither side is preferred by default.
8. If one direction has weak win rate AND non-positive average net PnL in recent trades, require stronger evidence before opening that direction. If a direction is on loss-streak cooldown (see context), do NOT open that side.
9. The per-pair and side history shown above is net of fees. A pair or specific side with avg PnL near zero or negative over multiple trades is a fee-eating churn.
10. Prefer pairs with clearly positive recent avg net PnL on the exact LONG/SHORT side you propose.
11. Mark OPEN YES for at most {MAX_ORDERS_PER_CYCLE} pairs. If no candidate has clear edge, return them with OPEN false rather than forcing a trade.

Respond ONLY valid JSON:
[
  {{"rank":1,"symbol":"BTCUSDT","direction":"LONG","confidence":84,"leverage":4,"margin_usdt":1.4,"size":0.00006,"possible":true,"open":true,"reason":"brief"}},
  ...
]
"""
    response = ask_llm(prompt)
    if not response:
        logger.warning("Using fallback signal ranking because LLM returned no response")
        return analyze_top_signals_fallback(tickers, balance)
    try:
        start, end = response.find("["), response.rfind("]")
        if start == -1 or end == -1: return []
        raw_signals = json.loads(response[start:end + 1])
        signals = []
        for item in raw_signals:
            symbol = str(item.get("symbol", "")).upper()
            direction = str(item.get("direction", "")).upper()
            if symbol not in ticker_map or direction not in ["LONG", "SHORT"]: continue
            leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, parse_int(item.get("leverage"), MIN_LEVERAGE)))
            signal = {
                "rank": parse_int(item.get("rank"), len(signals) + 1),
                "symbol": symbol,
                "direction": direction,
                "confidence": parse_int(item.get("confidence"), 0),
                "leverage": leverage,
                "margin_usdt": parse_float(item.get("margin_usdt"), 0.0),
                "size": parse_float(item.get("size"), 0.0),
                "possible": parse_bool(item.get("possible", False)),
                "open": parse_bool(item.get("open", False)),
                "reason": str(item.get("reason", ""))[:220],
                "price": parse_float(ticker_map[symbol].get("lastPr")),
            }
            signals.append(signal)
            if len(signals) >= TOP_SIGNAL_COUNT: break
        return signals
    except Exception as e:
        logger.error(f"Signal parse error: {e}")
        return []

def send_top_signals(signals, balance, open_count):
    if not signals:
        logger.info("No valid signals returned this cycle.")
        return
    lines = [f"📊 <b>Top {len(signals)} signals</b>\nBalance: <b>{balance:.4f} USDT</b>\nOpen positions: <b>{open_count}/{MAX_POSITIONS}</b>"]
    for s in signals:
        possible = "OK" if s["possible"] else "NO"
        open_mark = "OPEN" if s["open"] else "WATCH"
        lines.append(
            f"{s['rank']}. <b>{s['symbol']}</b> {s['direction']} | Conf: <b>{s['confidence']}%</b> | "
            f"Lev: <b>{s['leverage']}x</b> | Margin: <b>{s['margin_usdt']:.4f}</b> | {possible}/{open_mark}\n"
            f"{s['reason']}"
        )
    send_telegram("\n\n".join(lines))

def _signals_state_key(signals, open_count):
    """Cheap fingerprint of the current signal set so we only re-notify on real changes."""
    if not signals:
        return ("empty", open_count)
    return (
        open_count,
        tuple((s["symbol"], s["direction"], int(s["confidence"]), bool(s["open"])) for s in signals),
    )

def maybe_send_top_signals(signals, balance, open_count):
    """Throttled signal notif: notify when state changes OR cooldown elapsed.
    Stay silent on repeats even if a signal is marked OPEN — the actual
    trade open notification is what matters; the ranking is just context."""
    global last_signal_notif_time, last_signal_notif_state
    now = time.time()
    state = _signals_state_key(signals, open_count)
    state_changed = state != last_signal_notif_state
    cooldown_passed = (now - last_signal_notif_time) >= SIGNAL_NOTIF_COOLDOWN_MIN * 60
    if not (state_changed or cooldown_passed):
        return
    # Skip when positions are full and the signal set hasn't actually changed,
    # even if the cooldown elapsed — repeating identical signals is just noise.
    if open_count >= MAX_POSITIONS and not state_changed:
        return
    send_top_signals(signals, balance, open_count)
    last_signal_notif_time = now
    last_signal_notif_state = state

def normalize_order_size(size):
    if size <= 0: return 0.0
    if size >= 1:
        return math.floor(size * 100) / 100
    return math.floor(size * 100000000) / 100000000

def risk_leverage_cap(confidence):
    if confidence < 80:
        return LOW_CONFIDENCE_MAX_LEVERAGE
    if confidence < 90:
        return MID_CONFIDENCE_MAX_LEVERAGE
    return RISK_MAX_LEVERAGE

def liquidation_buffer_pct(leverage):
    if leverage <= 0: return 0.0
    stop_move_pct = STOP_LOSS_ROI_PCT / leverage
    estimated_liq_move_pct = 100.0 / leverage
    return estimated_liq_move_pct - stop_move_pct

def calculate_position_size(balance, signal, entry_price):
    if entry_price <= 0 or balance <= 0: return 0.0, 0.0, MIN_LEVERAGE
    target_notional = MIN_NOTIONAL * 1.03
    confidence = parse_int(signal.get("confidence"), 0)
    leverage_cap = risk_leverage_cap(confidence)
    margin_cap = min(balance * MAX_MARGIN_PER_TRADE_FRACTION, max(0.0, balance - MIN_FREE_BALANCE_USDT))
    if margin_cap <= 0:
        return 0.0, 0.0, MIN_LEVERAGE
    min_required_leverage = math.ceil(target_notional / margin_cap)
    requested_leverage = max(MIN_LEVERAGE, min(MAX_LEVERAGE, parse_int(signal.get("leverage"), MIN_LEVERAGE)))
    leverage = max(MIN_LEVERAGE, min(max(requested_leverage, min_required_leverage), leverage_cap))
    if leverage < min_required_leverage or liquidation_buffer_pct(leverage) < MIN_LIQUIDATION_BUFFER_PCT:
        return 0.0, 0.0, leverage
    margin = parse_float(signal.get("margin_usdt"), 0.0)
    size = parse_float(signal.get("size"), 0.0)
    if margin <= 0 and size > 0:
        margin = (size * entry_price) / leverage
    min_margin = target_notional / leverage
    if margin <= 0:
        margin = min_margin
    margin = min(max(margin, min_margin), margin_cap)
    size = (margin * leverage) / entry_price
    if margin <= 0 or margin > balance or size <= 0:
        return 0.0, 0.0, leverage
    return normalize_order_size(size), margin, leverage

def open_manual_trade(symbol, direction, margin_usdt=0.0, leverage=0):
    symbol = symbol.upper()
    direction = direction.upper()
    if direction not in ("LONG", "SHORT"):
        send_telegram("⚠️ Manual direction must be LONG or SHORT.")
        return
    ticker = next((t for t in get_tickers() if t.get("symbol") == symbol), None)
    if not ticker:
        send_telegram(f"⚠️ Symbol not found: {symbol}")
        return
    price = parse_float(ticker.get("lastPr"), 0.0)
    balance = get_strategy_balance()
    signal = {
        "confidence": 100,
        "leverage": leverage if leverage > 0 else RISK_MAX_LEVERAGE,
        "margin_usdt": margin_usdt,
        "size": 0.0,
    }
    size, margin, leverage = calculate_position_size(balance, signal, price)
    notional = size * price
    if price <= 0 or size <= 0 or margin <= 0 or notional < MIN_NOTIONAL:
        send_telegram(f"⚠️ Cannot open manual {direction} {symbol} with balance {balance:.4f} USDT.")
        return
    hold_side = "long" if direction == "LONG" else "short"
    side = "buy" if direction == "LONG" else "sell"
    tp_price, sl_price = calculate_roi_prices(price, hold_side, leverage)
    if DRY_RUN:
        save_trade_open(symbol, f"DRY_MANUAL_{direction}", price, size, leverage, 100)
        send_telegram(
            f"🧪 <b>DRY RUN MANUAL {direction} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
            f"Size: <b>{size}</b> | Margin: <b>{margin:.4f} USDT</b> | Notional: <b>{notional:.2f} USDT</b>\n"
            f"Leverage: <b>{leverage}x</b>\nTP: <b>{TAKE_PROFIT_ROI_PCT:.0f}% ROI</b> @ <b>{tp_price}</b>\n"
            f"SL: <b>{STOP_LOSS_ROI_PCT:.0f}% ROI</b> @ <b>{sl_price}</b>\n\nManual trades do not use the auto {MAX_POSITIONS}-pair limit."
        )
        logger.info(f"DRY RUN manual opened {direction} {symbol} @ {price} | Size: {size} | Lev: {leverage}x")
        return
    lev_res = set_leverage(symbol, leverage, hold_side)
    if lev_res.get("code") != "00000":
        send_telegram(f"⚠️ Manual leverage failed for {symbol}: {lev_res.get('msg')}")
        return
    res = place_order(symbol, side, size, hold_side, tp_price, sl_price)
    if res.get("code") == "00000":
        save_trade_open(symbol, f"MANUAL_{direction}", price, size, leverage, 100)
        send_telegram(
            f"🟢 <b>MANUAL {direction} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
            f"Size: <b>{size}</b> | Margin: <b>{margin:.4f} USDT</b> | Notional: <b>{notional:.2f} USDT</b>\n"
            f"Leverage: <b>{leverage}x</b>\nTP: <b>{TAKE_PROFIT_ROI_PCT:.0f}% ROI</b> @ <b>{tp_price}</b>\n"
            f"SL: <b>{STOP_LOSS_ROI_PCT:.0f}% ROI</b> @ <b>{sl_price}</b>\n\nManual trades do not use the auto {MAX_POSITIONS}-pair limit."
        )
        logger.info(f"Manual opened {direction} {symbol} @ {price} | Size: {size} | Lev: {leverage}x")
    else:
        send_telegram(f"⚠️ Manual order failed for {symbol}: {res.get('msg')}")
        logger.error(f"Manual order failed for {symbol}: {res.get('msg')}")

def calculate_roi_prices(entry_price, hold_side, leverage):
    price_move_tp = TAKE_PROFIT_ROI_PCT / (leverage * 100)
    price_move_sl = STOP_LOSS_ROI_PCT / (leverage * 100)
    if hold_side == "long":
        tp_price = entry_price * (1 + price_move_tp)
        sl_price = entry_price * (1 - price_move_sl)
    else:
        tp_price = entry_price * (1 - price_move_tp)
        sl_price = entry_price * (1 + price_move_sl)
    return round(tp_price, 8), round(sl_price, 8)

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

def calculate_position_roi_pct(position):
    entry_price = parse_float(position.get("openPriceAvg"), 0.0)
    current_price = float(position.get("markPrice", entry_price))
    leverage = max(1, parse_int(position.get("leverage"), MIN_LEVERAGE))
    size = get_position_size_value(position)
    hold_side = position.get("holdSide", "long")
    if entry_price <= 0 or current_price <= 0 or size <= 0: return 0.0
    gross_pnl = (current_price - entry_price) * size if hold_side == "long" else (entry_price - current_price) * size
    fee = estimate_round_trip_fee(entry_price, current_price, size)
    margin = (entry_price * size) / leverage
    if margin <= 0: return 0.0
    return ((gross_pnl - fee) / margin) * 100

def check_stop_loss(position, entry_price):
    return calculate_position_roi_pct(position) <= -STOP_LOSS_ROI_PCT

def check_trailing_stop(position_key, current_roi_pct):
    # Arm trailing only after the trade clears fees with margin to spare.
    if position_key not in trailing_stops:
        if current_roi_pct < TRAILING_ACTIVATE_ROI_PCT:
            return False
        trailing_stops[position_key] = current_roi_pct
        return False
    highest = trailing_stops[position_key]
    if current_roi_pct > highest:
        trailing_stops[position_key] = current_roi_pct
        return False
    # Never trail-out below the minimum net-profit floor — otherwise we'd
    # just be paying round-trip fees to scratch in and out.
    if current_roi_pct < MIN_TRAILING_PROFIT_ROI_PCT:
        return False
    drawdown_pct_of_peak = ((highest - current_roi_pct) / highest) * 100
    return drawdown_pct_of_peak >= TRAILING_STOP_PCT

def get_position_size_value(position):
    size = parse_float(position.get("size"), 0.0)
    if size <= 0:
        size = parse_float(position.get("available"), 0.0)
    if size <= 0:
        size = parse_float(position.get("total"), 0.0)
    return size

def estimate_position_net_pnl(position, current_price=None):
    entry_price = parse_float(position.get("openPriceAvg"), 0.0)
    current_price = parse_float(current_price, 0.0) if current_price is not None else parse_float(position.get("markPrice", entry_price), entry_price)
    hold_side = position.get("holdSide", "long")
    size = get_position_size_value(position)
    if entry_price <= 0 or current_price <= 0 or size <= 0:
        return 0.0, 0.0, 0.0, current_price, size
    net_pnl, fee = calculate_net_pnl(entry_price, current_price, size, hold_side)
    return net_pnl, fee, size, current_price, entry_price

def find_and_trade():
    global last_trade_time, force_trade, daily_loss_locked_date, consecutive_loss_cooldown_until
    positions = get_auto_strategy_positions()
    balance = get_strategy_balance()
    today_net_pnl = get_strategy_today_net_pnl()
    today = datetime.now().strftime("%Y-%m-%d")
    if today_net_pnl <= -MAX_DAILY_LOSS_USD:
        if daily_loss_locked_date != today:
            send_telegram(f"🛑 <b>Daily loss limit reached</b>\nNet PnL: <b>{today_net_pnl:.4f} USDT</b>\nLimit: <b>-{MAX_DAILY_LOSS_USD:.4f} USDT</b>\nNew entries paused for today.")
            daily_loss_locked_date = today
        logger.info(f"Daily loss limit reached: {today_net_pnl:.4f}/-{MAX_DAILY_LOSS_USD:.4f}; entries paused")
        force_trade = False
        return
    if time.time() < consecutive_loss_cooldown_until:
        remaining = int((consecutive_loss_cooldown_until - time.time()) / 60) + 1
        logger.info(f"Consecutive loss cooldown active ({remaining} min left); skipping new entries")
        force_trade = False
        return
    if not force_trade and last_trade_time and time.time() - last_trade_time < TRADE_COOLDOWN_MIN * 60:
        remaining = int(((TRADE_COOLDOWN_MIN * 60) - (time.time() - last_trade_time)) / 60) + 1
        logger.info(f"Trade cooldown active ({remaining} min left); skipping new entries")
        return
    if DRY_RUN:
        logger.info(f"Dry-run paper balance: {balance:.4f} USDT | Real balance: {get_balance():.4f} USDT")
    tickers = get_tickers()
    candidates = [
        t for t in tickers
        if t.get("symbol")
        and parse_float(t.get("lastPr")) > 0
        and ticker_quote_volume(t, parse_float(t.get("lastPr"))) >= MIN_QUOTE_VOLUME_USDT
    ]
    candidates = sorted(candidates, key=lambda x: ticker_quote_volume(x, parse_float(x.get("lastPr"))), reverse=True)[:SIGNAL_SCAN_COUNT]
    if not candidates:
        logger.info("No candidates found")
        force_trade = False
        return
    logger.info(f"Analyzing {len(candidates)} tickers...")
    update_blacklist()
    check_and_apply_loss_streak_cooldowns()
    signals = analyze_top_signals(candidates, balance)
    maybe_send_top_signals(signals, balance, len(positions))
    force_trade = False
    if len(positions) >= MAX_POSITIONS:
        logger.info(f"Max positions reached: {len(positions)}/{MAX_POSITIONS}; signals only")
        return
    ticker_map = {t["symbol"]: t for t in candidates}
    existing_symbols = {p["symbol"] for p in positions}
    preferred = [s for s in signals if s["open"]]
    order_candidates = preferred
    opened = 0
    max_to_open = min(MAX_ORDERS_PER_CYCLE, MAX_POSITIONS - len(positions))
    for signal in order_candidates:
        if opened >= max_to_open: break
        symbol = signal["symbol"]
        if symbol in existing_symbols: continue
        if symbol in blacklisted_pairs:
            logger.info(f"Skipping {symbol} - blacklisted (loss rate >= {BLACKLIST_LOSS_RATE_PCT:.0f}%)")
            continue
        if not direction_allowed(signal["direction"]):
            logger.info(f"Skipping {symbol} {signal['direction']} - direction blocked by recent performance / cooldown")
            continue
        bad_side_ev, side_stats = pair_direction_negative_ev(symbol, signal["direction"])
        if bad_side_ev:
            logger.info(f"Skipping {symbol} {signal['direction']} - weak pair+side history (last {side_stats['total']}: avg {side_stats['avg_pnl']:+.4f} USDT, WR {side_stats['win_rate']:.0f}%)")
            continue
        bad_ev, ev_stats = pair_negative_ev(symbol)
        if bad_ev:
            logger.info(f"Skipping {symbol} - negative EV (last {ev_stats['total']}: avg {ev_stats['avg_pnl']:+.4f} USDT, WR {ev_stats['win_rate']:.0f}%)")
            continue
        loss_streak, loss_streak_reason = pair_loss_streak_active(symbol)
        if loss_streak:
            logger.info(f"Skipping {symbol} - pair cooldown ({loss_streak_reason})")
            continue
        if signal["confidence"] < MIN_CONFIDENCE or not signal["possible"]: continue
        price = parse_float(ticker_map.get(symbol, {}).get("lastPr"), signal.get("price", 0.0))
        size, margin, leverage = calculate_position_size(balance, signal, price)
        notional = size * price
        if price <= 0 or size <= 0 or margin <= 0 or margin > balance or notional < MIN_NOTIONAL:
            logger.info(f"Skipping {symbol} - cannot meet minimum with balance/leverage")
            continue
        decision, confidence, reasoning = signal["direction"], signal["confidence"], signal["reason"]
        hold_side = "long" if decision == "LONG" else "short"
        side = "buy" if decision == "LONG" else "sell"
        tp_price, sl_price = calculate_roi_prices(price, hold_side, leverage)
        if DRY_RUN:
            dry_action = f"DRY_{decision}"
            save_trade_open(symbol, dry_action, price, size, leverage, confidence)
            last_trade_time = time.time()
            msg = (f"🧪 <b>DRY RUN {decision} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
                   f"Size: <b>{size}</b> | Margin: <b>{margin:.4f} USDT</b> | Notional: <b>{notional:.2f} USDT</b>\n"
                   f"Leverage: <b>{leverage}x</b>\nConfidence: <b>{confidence}%</b>\n"
                   f"TP: <b>{TAKE_PROFIT_ROI_PCT:.0f}% ROI</b> @ <b>{tp_price}</b>\n"
                   f"SL: <b>{STOP_LOSS_ROI_PCT:.0f}% ROI</b> @ <b>{sl_price}</b>\n"
                   f"Fee model: <b>{TAKER_FEE_RATE * 100:.2f}% taker each side</b>\n\n💡 {reasoning}")
            send_telegram(msg)
            logger.info(f"DRY RUN opened {decision} {symbol} @ {price} | Size: {size} | Lev: {leverage}x")
            opened += 1
            existing_symbols.add(symbol)
            continue
        lev_res = set_leverage(symbol, leverage, hold_side)
        if lev_res.get("code") != "00000":
            logger.warning(f"Skipping {symbol} - leverage failed: {lev_res.get('msg')}")
            continue
        res = place_order(symbol, side, size, hold_side, tp_price, sl_price)
        if res.get("code") == "00000":
            save_trade_open(symbol, decision, price, size, leverage, confidence)
            last_trade_time = time.time()
            msg = (f"🟢 <b>{decision} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
                   f"Size: <b>{size}</b> | Margin: <b>{margin:.4f} USDT</b> | Notional: <b>{notional:.2f} USDT</b>\n"
                   f"Leverage: <b>{leverage}x</b>\nConfidence: <b>{confidence}%</b>\n"
                   f"TP: <b>{TAKE_PROFIT_ROI_PCT:.0f}% ROI</b> @ <b>{tp_price}</b>\n"
                   f"SL: <b>{STOP_LOSS_ROI_PCT:.0f}% ROI</b> @ <b>{sl_price}</b>\n\n💡 {reasoning}")
            send_telegram(msg)
            logger.info(f"Opened {decision} {symbol} @ {price} | Size: {size} | Lev: {leverage}x")
            opened += 1
            existing_symbols.add(symbol)
        else:
            logger.error(f"Order failed for {symbol}: {res.get('msg')}")
    if opened == 0:
        logger.info("No orders opened this cycle")

def manage_positions():
    global consecutive_losses, consecutive_loss_cooldown_until
    positions = get_strategy_positions()
    if not positions: return
    for p in positions:
        symbol, hold_side, entry = p["symbol"], p.get("holdSide", "long"), float(p.get("openPriceAvg", 0))
        trail_key = position_state_key(symbol, hold_side)
        if DRY_RUN:
            ticker = next((t for t in get_tickers() if t.get("symbol") == symbol), {})
            current = parse_float(ticker.get("lastPr"), entry)
            leverage = max(1, parse_int(p.get("leverage"), MIN_LEVERAGE))
            net_pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
            pnl = net_pnl
            p["markPrice"] = current
            p["unrealizedPL"] = pnl
            p["leverage"] = leverage
        else:
            current = float(p.get("markPrice", 0))
            net_pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
            pnl = net_pnl if size > 0 else float(p.get("unrealizedPL", 0))
        roi_pct = calculate_position_roi_pct(p)
        if roi_pct >= TAKE_PROFIT_ROI_PCT:
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                clear_trailing_stop(symbol, hold_side)
                consecutive_losses = 0
                prefix = "DRY RUN " if DRY_RUN else ""
                send_telegram(f"✅ <b>{prefix}TAKE PROFIT</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nNet ROI: <b>+{roi_pct:.2f}%</b>\nNet PnL: <b>+{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                logger.info(f"{prefix}TP hit {symbol} | Net ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f} | Fee: {fee:.4f}")
                continue
        if check_stop_loss(p, entry):
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                clear_trailing_stop(symbol, hold_side)
                consecutive_losses += 1
                prefix = "DRY RUN " if DRY_RUN else ""
                send_telegram(f"🛑 <b>{prefix}STOP LOSS</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nNet ROI: <b>{roi_pct:.2f}%</b>\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>\nConsecutive losses: {consecutive_losses}")
                logger.info(f"{prefix}SL hit {symbol} | Net ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f} | Fee: {fee:.4f}")
                if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                    consecutive_loss_cooldown_until = time.time() + CONSECUTIVE_LOSS_COOLDOWN_MIN * 60
                    send_telegram(f"⏸️ <b>Cooldown</b>\nReached {consecutive_losses} consecutive losses (limit {CONSECUTIVE_LOSS_LIMIT}).\nNew entries paused for <b>{CONSECUTIVE_LOSS_COOLDOWN_MIN} min</b>.")
                    logger.warning(f"Consecutive loss limit hit ({consecutive_losses}); cooldown {CONSECUTIVE_LOSS_COOLDOWN_MIN} min")
                    consecutive_losses = 0
                continue
        if check_trailing_stop(trail_key, roi_pct):
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                peak = trailing_stops.pop(trail_key, roi_pct)
                trailing_stops.pop(symbol, None)
                if pnl <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                prefix = "DRY RUN " if DRY_RUN else ""
                emoji = "🔻" if pnl <= 0 else "✅"
                send_telegram(f"{emoji} <b>{prefix}TRAILING STOP</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nPeak ROI: <b>+{peak:.2f}%</b> → Now: <b>{roi_pct:.2f}%</b>\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                logger.info(f"{prefix}Trailing stop hit {symbol} | Peak ROI: {peak:.2f}% | Exit ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f}")
                continue
        age_hours = position_age_hours(p)
        if MAX_HOLD_HOURS > 0 and age_hours >= MAX_HOLD_HOURS:
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            if res.get("code") == "00000":
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                clear_trailing_stop(symbol, hold_side)
                if pnl <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                prefix = "DRY RUN " if DRY_RUN else ""
                emoji = "⏱️" if pnl >= 0 else "⏱️🔻"
                send_telegram(f"{emoji} <b>{prefix}TIME STOP</b>\n{hold_side.upper()} {symbol}\nHeld: <b>{age_hours:.1f}h</b> (limit {MAX_HOLD_HOURS}h)\nEntry: {entry:.6f} → Exit: {current:.6f}\nNet ROI: <b>{roi_pct:.2f}%</b>\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                logger.info(f"{prefix}Time stop {symbol} | Age: {age_hours:.1f}h | Net ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f}")
                continue

def handle_commands():
    global bot_running, force_trade, consecutive_losses, consecutive_loss_cooldown_until
    logger.info("Telegram handler started")
    while bot_running:
        try:
            updates = get_telegram_updates()
            for u in updates:
                msg, chat_id, text = u.get("message", {}), str(u.get("message", {}).get("chat", {}).get("id", "")), u.get("message", {}).get("text", "").strip().lower()
                if chat_id not in TELEGRAM_CHAT_IDS: continue
                if text == "/status":
                    positions, auto_positions, manual_count = get_position_counts()
                    balance, daily_pnl = get_strategy_balance(), get_strategy_today_net_pnl()
                    mode = f"{'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}"
                    if not positions:
                        send_telegram(f"📊 <b>Status</b>\nMode: <b>{mode}</b>\nBalance: <b>{balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nAuto positions: <b>0/{MAX_POSITIONS}</b>\nManual positions: <b>0</b>\nConsecutive losses: <b>{consecutive_losses}</b>")
                    else:
                        lines = [f"📊 <b>Status</b>\nMode: <b>{mode}</b>\nBalance: <b>{balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nAuto positions: <b>{len(auto_positions)}/{MAX_POSITIONS}</b>\nManual positions: <b>{manual_count}</b>\nConsecutive losses: <b>{consecutive_losses}</b>\n"]
                        for p in positions:
                            entry = float(p.get("openPriceAvg", 0))
                            if DRY_RUN:
                                ticker = next((t for t in get_tickers() if t.get("symbol") == p["symbol"]), {})
                                current = parse_float(ticker.get("lastPr"), entry)
                                pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
                            else:
                                current = float(p.get("markPrice", 0))
                                pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
                            emoji = "🟢" if pnl > 0 else "🔴"
                            pnl_pct = ((current - entry) / entry * 100) if p.get("holdSide") == "long" else ((entry - current) / entry * 100)
                            lines.append(f"{emoji} {p.get('holdSide','').upper()} {p['symbol']}\nEntry: {entry:.6f} | Now: {current:.6f}\nNet PnL: <b>{pnl:.4f} USDT ({pnl_pct:+.2f}%)</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                        send_telegram("\n\n".join(lines))
                elif text == "/balance":
                    balance, daily_pnl = get_strategy_balance(), get_strategy_today_net_pnl()
                    real_balance = get_balance() if DRY_RUN else balance
                    mode = f"{'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}"
                    send_telegram(f"💰 <b>Balance</b>\nMode: <b>{mode}</b>\nAvailable: <b>{balance:.4f} USDT</b>\nReal balance: <b>{real_balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nMax daily loss: <b>{MAX_DAILY_LOSS_USD} USDT</b>")
                elif text == "/history":
                    summary = get_trade_summary()
                    if not summary:
                        send_telegram("📈 Belum ada trade history.")
                    else:
                        send_telegram(f"📈 <b>Trade History</b>\n\nTotal trades: <b>{summary['total_trades']}</b>\nWin rate: <b>{summary['win_rate']}</b>\nAvg PnL: <b>{summary['avg_pnl']} USDT</b>\nBest pair: <b>{summary['best_pair']}</b>\nWorst pair: <b>{summary['worst_pair']}</b>\n\n<b>Last 10 Trades:</b>\n{summary['last_10']}")
                elif text == "/trade":
                    force_trade = True
                    consecutive_losses = 0
                    consecutive_loss_cooldown_until = 0
                    send_telegram("⚡ Starting analysis...")
                elif text.startswith("/mode"):
                    parts = text.split()
                    if len(parts) == 1:
                        send_telegram(f"⚙️ <b>Mode</b>\nCurrent: <b>{TRADE_MODE.upper()}</b>\nAvailable: <b>NORMAL</b>, <b>SCALPING</b>\nUse /mode normal or /mode scalping")
                    else:
                        requested = parts[1].strip().lower()
                        if requested in ("biasa", "normal", "trade"):
                            requested = "normal"
                        elif requested in ("scalp", "scalping"):
                            requested = "scalping"
                        else:
                            send_telegram("⚠️ Mode tidak dikenal. Pilih: /mode normal atau /mode scalping")
                            continue
                        if apply_trade_mode(requested):
                            send_telegram(f"✅ <b>Mode changed</b>\nCurrent: <b>{TRADE_MODE.upper()}</b>\nTP: <b>{TAKE_PROFIT_ROI_PCT:.0f}% ROI</b>\nSL: <b>{STOP_LOSS_ROI_PCT:.0f}% ROI</b>\nSleep: <b>{SLEEP_MINUTES} min</b>")
                            logger.info(f"Trade mode changed to {TRADE_MODE.upper()}")
                        else:
                            send_telegram("⚠️ Gagal mengubah mode.")
                elif text.startswith("/long") or text.startswith("/short"):
                    parts = text.split()
                    direction = "LONG" if text.startswith("/long") else "SHORT"
                    if len(parts) < 2:
                        send_telegram(f"⚠️ Use /{direction.lower()} SYMBOL [margin_usdt] [leverage]\nExample: /{direction.lower()} BTCUSDT 2 8")
                        continue
                    symbol = parts[1].upper()
                    margin = parse_float(parts[2], 0.0) if len(parts) >= 3 else 0.0
                    leverage = parse_int(parts[3], 0) if len(parts) >= 4 else 0
                    open_manual_trade(symbol, direction, margin, leverage)
                elif text.startswith("/close"):
                    parts = text.split()
                    if len(parts) == 1:
                        send_telegram("⏳ Closing all positions...")
                        close_all_positions()
                    else:
                        sym = parts[1].upper()
                        positions = get_strategy_positions() if DRY_RUN else get_positions()
                        pos = next((p for p in positions if p["symbol"].upper() == sym), None)
                        if not pos:
                            send_telegram(f"⚠️ No position for {sym}")
                        else:
                            hold = pos.get("holdSide", "long")
                            price = float(pos.get("markPrice", pos.get("openPriceAvg", 0)))
                            pnl, fee, size, current, entry = estimate_position_net_pnl(pos, price)
                            res = {"code": "00000"} if DRY_RUN else close_position_api(sym, hold)
                            if res.get("code") == "00000":
                                save_trade_close_by_id(pos["id"], price, pnl) if DRY_RUN else save_trade_close(sym, price, pnl, hold)
                                clear_trailing_stop(sym, hold)
                                emoji = "✅" if pnl > 0 else "❌"
                                prefix = "DRY RUN " if DRY_RUN else ""
                                send_telegram(f"{emoji} <b>{prefix}CLOSED</b> {hold.upper()} {sym}\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                            else:
                                send_telegram(f"⚠️ Failed to close {sym}: {res.get('msg')}")
                elif text == "/stop":
                    send_telegram("🛑 Bot stopped.")
                    bot_running = False
                elif text == "/help":
                    send_telegram(f"📋 <b>Commands</b>\n\n/status — positions + PnL\n/balance — balance + daily PnL\n/history — trade stats\n/trade — force trade now (clears cooldown)\n/mode [normal|scalping] — switch trading mode\n/long SYMBOL [margin] [leverage] — manual long\n/short SYMBOL [margin] [leverage] — manual short\n/close [SYMBOL] — close position(s)\n/stop — stop bot\n\n<b>Settings:</b>\nMode: {TRADE_MODE.upper()}\nAuto max positions: {MAX_POSITIONS}\nManual trades: not counted in auto limit\nTP: {TAKE_PROFIT_ROI_PCT:.0f}% ROI\nSL: {STOP_LOSS_ROI_PCT:.0f}% ROI\nTrailing: arm at +{TRAILING_ACTIVATE_ROI_PCT:.1f}% ROI, exit on {TRAILING_STOP_PCT:.1f}% drawdown, floor {MIN_TRAILING_PROFIT_ROI_PCT:.1f}% ROI\nTime stop: {MAX_HOLD_HOURS}h max hold\nMax daily loss: ${MAX_DAILY_LOSS_USD}\nConsec. loss limit: {CONSECUTIVE_LOSS_LIMIT} → {CONSECUTIVE_LOSS_COOLDOWN_MIN} min cooldown")
            time.sleep(1)
        except Exception as e:
            logger.error(f"handle_commands error: {e}")
            time.sleep(1)

def main():
    global bot_running
    logger.info("=== Bitget LLM Bot V2 (Learning Edition) ===")
    send_telegram(f"🤖 <b>Bitget LLM Bot V2</b>\n🧠 <b>Learning Edition</b>\n\nMode: <b>{'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}</b>\nMax positions: <b>{MAX_POSITIONS}</b>\nScan: <b>{SIGNAL_SCAN_COUNT} tickers / {SLEEP_MINUTES} min</b>\nTop signals: <b>{TOP_SIGNAL_COUNT}</b>\nTP: <b>{TAKE_PROFIT_ROI_PCT:.0f}% ROI</b>\nSL: <b>{STOP_LOSS_ROI_PCT:.0f}% ROI</b>\nMin confidence: <b>{MIN_CONFIDENCE}%</b>\n\nType /help for commands.")
    init_db()
    cleanup_stale_dry_run_positions()
    t = threading.Thread(target=handle_commands, daemon=True)
    t.start()
    while bot_running:
        try:
            positions, auto_positions, manual_count = get_position_counts()
            balance = get_strategy_balance()
            real_balance = get_balance() if DRY_RUN else balance
            logger.info(f"Mode: {'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()} | Paper balance: {balance:.4f} | Real balance: {real_balance:.4f} | Auto positions: {len(auto_positions)}/{MAX_POSITIONS} | Manual positions: {manual_count}")
            if positions:
                for p in positions:
                    if DRY_RUN:
                        ticker = next((t for t in get_tickers() if t.get("symbol") == p["symbol"]), {})
                        entry = float(p.get("openPriceAvg", 0))
                        pnl, fee, size, current, entry = estimate_position_net_pnl(p, parse_float(ticker.get("lastPr"), entry))
                    else:
                        pnl, fee, size, current, entry = estimate_position_net_pnl(p, float(p.get("markPrice", 0)))
                    logger.info(f"Position: {p.get('holdSide','').upper()} {p['symbol']} | Net PnL: {pnl:.4f} | Est. fees: {fee:.4f}")
                manage_positions()
            find_and_trade()
            if DRY_RUN and get_strategy_positions():
                logger.info(f"Dry-run positions active; sleeping {DRY_RUN_POLL_SECONDS} sec...")
                time.sleep(DRY_RUN_POLL_SECONDS)
            elif not force_trade:
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
    ensure_daemonized()
    while True:
        try:
            main()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Fatal bot error: {e}")
            time.sleep(5)
            continue
        if not bot_running:
            break
        logger.warning("Bot main loop exited unexpectedly; restarting in 5 sec...")
        time.sleep(5)
