import os, sys, subprocess, time, logging, json, requests, hmac, hashlib, base64, math, threading, sqlite3, re, ast
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
LLM_MODEL = os.environ.get("NVIDIA_LLM_MODEL", "meta/llama-4-maverick-17b-128e-instruct")
VIRTUALS_API_KEY = os.environ.get("VIRTUALS_API_KEY", "")
VIRTUALS_BASE_URL = "https://compute.virtuals.io/v1"
VIRTUALS_MODEL = os.environ.get("VIRTUALS_MODEL", "anthropic-claude-opus-4-8")
TOKENROUTER_API_KEY = os.environ.get("TOKENROUTER_API_KEY", "")
TOKENROUTER_BASE_URL = os.environ.get("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1").rstrip("/")
TOKENROUTER_MODEL = os.environ.get("TOKENROUTER_MODEL", "MiniMax-M3")
LLM_FALLBACK_MODELS = [
    "deepseek-ai/deepseek-v4-flash",
    "mistralai/mistral-large-3-675b-instruct-2512",
    "qwen/qwen3.5-122b-a10b",
    "meta/llama-3.3-70b-instruct",
]
VIRTUALS_FALLBACK_MODELS = [
    "anthropic-claude-opus-4-8-fast",
    "anthropic-claude-sonnet-4-6",
    "openai-gpt-55-pro",
    "openai-gpt-55",
    "google-gemini-3-1-pro-preview",
    "deepseek-deepseek-v4-pro",
    "deepseek-deepseek-v4-flash",
    "google-gemini-3-flash-preview",
]
TOKENROUTER_FALLBACK_MODELS = []
LLM_PROVIDER_LABELS = {
    "nvidia": "NVIDIA",
    "virtuals": "VIRTUALS",
    "tokenrouter": "TOKENROUTER",
}
SUPPORTED_LLM_PROVIDERS = tuple(LLM_PROVIDER_LABELS.keys())
LLM_PROVIDER_CODES = {
    "nvidia": "n",
    "virtuals": "v",
    "tokenrouter": "t",
}
LLM_PROVIDER_BY_CODE = {v: k for k, v in LLM_PROVIDER_CODES.items()}
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "nvidia").strip().lower()
if LLM_PROVIDER == "tok3nrouter":
    LLM_PROVIDER = "tokenrouter"
if LLM_PROVIDER not in SUPPORTED_LLM_PROVIDERS:
    logger.warning(f"Unknown LLM_PROVIDER={LLM_PROVIDER}; using nvidia")
    LLM_PROVIDER = "nvidia"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHAT_IDS = {c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", TELEGRAM_CHAT_ID).split(",") if c.strip()}
DRY_RUN = env_bool("DRY_RUN", env_bool("BITGET_DRY_RUN", True))
DRY_RUN_BALANCE = env_float("DRY_RUN_BALANCE", 5.0)
DRY_RUN_POLL_SECONDS = env_int("DRY_RUN_POLL_SECONDS", 15)
LLM_MANAGE_ENTRY = env_bool("LLM_MANAGE_ENTRY", True)
TRADE_MODE = os.environ.get("TRADE_MODE", os.environ.get("BITGET_TRADE_MODE", "scalping")).strip().lower()
TAKER_FEE_RATE = 0.0006
LLM_ERROR_COOLDOWN_SECONDS = 300
LLM_REQUEST_TIMEOUT_SECONDS = 30
LLM_TIMEOUT_MODEL_COOLDOWN_SECONDS = env_int("LLM_TIMEOUT_MODEL_COOLDOWN_SECONDS", 300)
LLM_FAILURE_MODEL_COOLDOWN_SECONDS = env_int("LLM_FAILURE_MODEL_COOLDOWN_SECONDS", 120)
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
PAIR_DIRECTION_EDGE_MIN_TRADES = env_int("PAIR_DIRECTION_EDGE_MIN_TRADES", 3)
PAIR_DIRECTION_EDGE_MIN_WIN_RATE = env_float("PAIR_DIRECTION_EDGE_MIN_WIN_RATE", 55.0)
PAIR_DIRECTION_EDGE_MIN_AVG_PNL = env_float("PAIR_DIRECTION_EDGE_MIN_AVG_PNL", 0.0)
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
MAX_MARGIN_PER_TRADE_FRACTION = env_float("MAX_MARGIN_PER_TRADE_FRACTION", 0.30)
DRY_RUN_TARGET_MARGIN_PER_TRADE_FRACTION = env_float("DRY_RUN_TARGET_MARGIN_PER_TRADE_FRACTION", 0.45)
MIN_FREE_BALANCE_USDT = 0.20
MIN_LIQUIDATION_BUFFER_PCT = 5.0
MARGIN_MODE, PRODUCT_TYPE, MARGIN_COIN = "isolated", "USDT-FUTURES", "USDT"
SLEEP_MINUTES = 5 if TRADE_MODE == "scalping" else 60

MAX_POSITIONS = max(1, env_int("MAX_POSITIONS", env_int("MAX_PAIRS", 2)))
MAX_ORDERS_PER_CYCLE = max(1, min(MAX_POSITIONS, env_int("MAX_ORDERS_PER_CYCLE", 1)))
FORCE_TRADE_ORDERS_PER_COMMAND = 1
TAKE_PROFIT_ROI_PCT, STOP_LOSS_ROI_PCT = (10.0, 6.0) if TRADE_MODE == "scalping" else (70.0, 40.0)
MAX_DAILY_LOSS_USD, TRADE_COOLDOWN_MIN = 0.75, 10
TRAILING_STOP_PCT, MIN_CONFIDENCE = (2.0, 80) if TRADE_MODE == "scalping" else (3.0, 70)
TRAILING_ACTIVATE_ROI_PCT = 8.0 if TRADE_MODE == "scalping" else 20.0
MIN_TRAILING_PROFIT_ROI_PCT = 5.0 if TRADE_MODE == "scalping" else 10.0
CONSECUTIVE_LOSS_LIMIT = 3
AUTO_OPEN_CONFIDENCE_SCALPING = env_int("AUTO_OPEN_CONFIDENCE_SCALPING", 85)
AUTO_OPEN_CONFIDENCE_NORMAL = env_int("AUTO_OPEN_CONFIDENCE_NORMAL", 83)
RECENT_PROFIT_WINDOW = env_int("RECENT_PROFIT_WINDOW", 10)
RECENT_PROFIT_MIN_TRADES = env_int("RECENT_PROFIT_MIN_TRADES", 5)
RECENT_PROFIT_MIN_WIN_RATE = env_float("RECENT_PROFIT_MIN_WIN_RATE", 60.0)
RECENT_DEFENSE_CONFIDENCE_BONUS = env_int("RECENT_DEFENSE_CONFIDENCE_BONUS", 4)
AUTO_OPEN_TARGET_WIN_RATE = env_float("AUTO_OPEN_TARGET_WIN_RATE", 65.0)
MIN_REWARD_RISK_RATIO = env_float("MIN_REWARD_RISK_RATIO", 1.35)
PROFIT_GUARD_MAX_LEVERAGE = env_int("PROFIT_GUARD_MAX_LEVERAGE", 4)
PROFIT_GUARD_MAX_LEVERAGE_CONFIDENCE = env_int("PROFIT_GUARD_MAX_LEVERAGE_CONFIDENCE", 92)
PROFIT_GUARD_SIDE_MIN_TRADES = env_int("PROFIT_GUARD_SIDE_MIN_TRADES", 2)
PROFIT_GUARD_SIDE_MIN_WIN_RATE = env_float("PROFIT_GUARD_SIDE_MIN_WIN_RATE", 50.0)
PROFIT_GUARD_PAIR_MIN_WIN_RATE = env_float("PROFIT_GUARD_PAIR_MIN_WIN_RATE", 55.0)
PROFIT_GUARD_UNKNOWN_HISTORY_CONFIDENCE = env_int("PROFIT_GUARD_UNKNOWN_HISTORY_CONFIDENCE", 92)
TIMEFRAMES = ["15m", "1H", "4H"]
SIGNAL_SCAN_COUNT, TOP_SIGNAL_COUNT = 50, 10
DB_PATH = "/root/trade_history.db"

bot_running, force_trade, force_open_trade, last_update_id = True, False, False, 0
last_trade_time, daily_pnl = 0, 0.0
trailing_stops, consecutive_losses, blacklisted_pairs = {}, 0, set()
llm_cooldown_until, daily_loss_locked_date = 0, None
consecutive_loss_cooldown_until = 0
llm_disabled_models = set()
llm_model_cooldowns = {}  # model -> timestamp until which it's on cooldown
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
    if "LONG" in action:
        return "long"
    if "SHORT" in action:
        return "short"
    return "long"

def action_direction(action):
    action = str(action).upper()
    if "LONG" in action:
        return "LONG"
    if "SHORT" in action:
        return "SHORT"
    return None

def position_state_key(symbol, hold_side):
    return f"{symbol}:{str(hold_side).lower()}"

def normalize_hold_side(hold_side):
    hold_side = str(hold_side or "").strip().lower()
    if hold_side in ("short", "sell"):
        return "short"
    return "long"

def clear_trailing_stop(symbol, hold_side):
    hold_side = normalize_hold_side(hold_side)
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
        return {(symbol, normalize_hold_side(direction_from_action(action))) for symbol, action in rows}
    except:
        return set()

def get_auto_strategy_positions():
    positions = get_strategy_positions()
    if DRY_RUN:
        return [p for p in positions if not is_manual_action(p.get("action", ""))]
    manual_keys = get_open_manual_position_keys()
    return [p for p in positions if (p.get("symbol"), normalize_hold_side(p.get("holdSide", "long"))) not in manual_keys]

def get_position_counts():
    all_positions = get_strategy_positions()
    auto_positions = get_auto_strategy_positions()
    manual_count = max(0, len(all_positions) - len(auto_positions))
    return all_positions, auto_positions, manual_count

def get_strategy_balance():
    if not DRY_RUN:
        return get_balance()
    closed_pnl = 0.0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute("SELECT SUM(pnl) FROM trades WHERE closed_at IS NOT NULL AND pnl IS NOT NULL AND action NOT LIKE 'STALE_%'")
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            closed_pnl = row[0]
    except:
        pass
    open_pnl = get_open_dry_run_net_pnl()
    return DRY_RUN_BALANCE + closed_pnl + open_pnl

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
    return get_today_pnl()

def estimate_round_trip_fee(entry_price, exit_price, size):
    entry_notional = abs(entry_price * size)
    exit_notional = abs(exit_price * size)
    return (entry_notional + exit_notional) * TAKER_FEE_RATE

def calculate_net_pnl(entry_price, exit_price, size, hold_side):
    hold_side = normalize_hold_side(hold_side)
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
    if direction_cooldown_active(direction):
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

def direction_cooldown_active(direction):
    direction = str(direction).upper()
    return time.time() < direction_cooldowns.get(direction, 0)

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

def get_recent_trade_stats(limit=RECENT_PROFIT_WINDOW):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.execute(
            """SELECT pnl FROM trades
               WHERE closed_at IS NOT NULL AND action NOT LIKE 'STALE_%'
               ORDER BY closed_at DESC LIMIT ?""",
            (limit,))
        rows = [parse_float(r[0], 0.0) for r in cur.fetchall() if r[0] is not None]
        conn.close()
    except Exception:
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    total = len(rows)
    if total == 0:
        return {"total": 0, "wins": 0, "win_rate": 0.0, "avg_pnl": 0.0}
    wins = sum(1 for pnl in rows if pnl > 0)
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

def pair_direction_has_edge(symbol, direction):
    s = get_pair_direction_recent_stats(symbol, direction)
    has_edge = (
        s["total"] >= PAIR_DIRECTION_EDGE_MIN_TRADES
        and s["avg_pnl"] > PAIR_DIRECTION_EDGE_MIN_AVG_PNL
        and s["win_rate"] >= PAIR_DIRECTION_EDGE_MIN_WIN_RATE
    )
    return has_edge, s

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
    hold_side = normalize_hold_side(hold_side)
    body = {"symbol": symbol, "productType": PRODUCT_TYPE, "holdSide": hold_side}
    return api_post("/api/v2/mix/order/close-positions", body)

def close_position_succeeded(res, symbol, hold_side):
    """Bitget flash-close may return code 00000 with per-symbol failures."""
    if res.get("code") != "00000":
        return False, res.get("msg", "API returned non-success code")
    data = res.get("data") or {}
    if not isinstance(data, dict):
        return True, ""
    symbol = str(symbol).upper()
    hold_side = normalize_hold_side(hold_side)
    failures = data.get("failureList") or data.get("failureList".lower()) or []
    if isinstance(failures, dict):
        failures = [failures]
    for item in failures:
        if not isinstance(item, dict):
            continue
        item_symbol = str(item.get("symbol", "")).upper()
        item_side = normalize_hold_side(item.get("holdSide", hold_side))
        if (not item_symbol or item_symbol == symbol) and item_side == hold_side:
            reason = item.get("errorMsg") or item.get("msg") or item.get("errorCode") or "close failed"
            return False, str(reason)
    successes = data.get("successList") or data.get("successList".lower()) or []
    if isinstance(successes, dict):
        successes = [successes]
    if successes:
        for item in successes:
            if not isinstance(item, dict):
                continue
            item_symbol = str(item.get("symbol", "")).upper()
            item_side = normalize_hold_side(item.get("holdSide", hold_side))
            if (not item_symbol or item_symbol == symbol) and item_side == hold_side:
                return True, ""
        return False, "symbol/side missing from close successList"
    return True, ""

def close_all_positions():
    positions = get_strategy_positions() if DRY_RUN else get_positions()
    for p in positions:
        symbol, hold = p["symbol"], normalize_hold_side(p.get("holdSide", "long"))
        price = parse_float(p.get("markPrice", p.get("openPriceAvg", 0)), 0.0)
        pnl, fee, size, current, entry = estimate_position_net_pnl(p, price)
        if DRY_RUN:
            res = {"code": "00000"}
        else:
            res = close_position_api(symbol, hold)
        ok, close_reason = close_position_succeeded(res, symbol, hold)
        if ok:
            save_trade_close_by_id(p["id"], price, pnl) if DRY_RUN else save_trade_close(symbol, price, pnl, hold)
            emoji = "✅" if pnl > 0 else "❌"
            prefix = "DRY RUN " if DRY_RUN else ""
            send_telegram(f"{emoji} <b>{prefix}CLOSED</b> {hold.upper()} {symbol}\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
            logger.info(f"{prefix}Closed {hold} {symbol} | Net PnL: {pnl:.4f} | Fee: {fee:.4f}")
        else:
            send_telegram(f"⚠️ Failed to close {hold.upper()} {symbol}: {close_reason}")
            logger.error(f"Close failed for {hold} {symbol}: {close_reason} | response={json.dumps(res, ensure_ascii=False)}")

def send_telegram(msg):
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}, timeout=10)
        except: pass

def send_telegram_buttons(msg, buttons, chat_id=None):
    targets = [chat_id] if chat_id else list(TELEGRAM_CHAT_IDS)
    for cid in targets:
        try:
            reply_markup = {
                "inline_keyboard": [
                    [{"text": text, "callback_data": cb_data} for text, cb_data in row]
                    for row in buttons
                ]
            }
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "HTML", "reply_markup": reply_markup}, timeout=10)
            if r.status_code != 200:
                logger.error(f"sendMessage failed (chat {cid}): {r.status_code} {r.text[:200]}")
        except Exception as e:
            logger.error(f"sendMessage error (chat {cid}): {e}")

def edit_message_buttons(chat_id, message_id, msg, buttons):
    try:
        reply_markup = {
            "inline_keyboard": [
                [{"text": text, "callback_data": cb_data} for text, cb_data in row]
                for row in buttons
            ]
        }
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
            json={"chat_id": chat_id, "message_id": message_id, "text": msg, "parse_mode": "HTML", "reply_markup": reply_markup}, timeout=10)
        if r.status_code != 200:
            logger.error(f"editMessageText failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.error(f"editMessageText error: {e}")

def main_menu():
    entry_label = "🤖 Auto TP/SL ✅" if LLM_MANAGE_ENTRY else "🤖 Auto TP/SL ❌"
    return [
        [("📊 Status", "menu:status"), ("💰 Balance", "menu:balance")],
        [("📈 History", "menu:history"), ("⚡ Trade", "menu:trade")],
        [("⚡ Force", "menu:forcetrade"), ("🧠 Model", "menu:model")],
        [("🔌 Provider", "menu:provider"), ("📄 Paper/Live", "menu:paper")],
        [("⚙️ Mode", "menu:mode"), (entry_label, "menu:entrymode")],
        [("🛑 Stop", "menu:stop"), ("📋 Help", "menu:help")],
    ]

def answer_callback(callback_query_id, text=""):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text}, timeout=10)
        if r.status_code != 200:
            logger.error(f"answerCallbackQuery failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.error(f"answerCallbackQuery error: {e}")

def get_telegram_updates():
    global last_update_id
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
            params={"offset": last_update_id + 1, "timeout": 5}, timeout=10)
        updates = r.json().get("result", [])
        if updates: last_update_id = updates[-1]["update_id"]
        return updates
    except: return []

def provider_model_list(provider):
    if provider == "virtuals":
        return [VIRTUALS_MODEL] + VIRTUALS_FALLBACK_MODELS
    if provider == "tokenrouter":
        return [TOKENROUTER_MODEL] + TOKENROUTER_FALLBACK_MODELS
    return [LLM_MODEL] + LLM_FALLBACK_MODELS

def provider_primary_model(provider):
    if provider == "virtuals":
        return VIRTUALS_MODEL
    if provider == "tokenrouter":
        return TOKENROUTER_MODEL
    return LLM_MODEL

def active_llm_model():
    return provider_primary_model(LLM_PROVIDER)

def provider_button_rows():
    rows = []
    for provider in SUPPORTED_LLM_PROVIDERS:
        label = LLM_PROVIDER_LABELS[provider]
        rows.append([(f"{label} ✅" if LLM_PROVIDER == provider else label, f"prov:{provider}")])
    rows.append([("🔙 Menu", "menu:main")])
    return rows

def llm_request_payload(provider, model, prompt):
    content = prompt
    if provider == "tokenrouter":
        content = [{"type": "text", "text": prompt}]
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4096,
    }

def _try_llm_provider(prompt, name, base_url, api_key, models):
    global llm_model_cooldowns
    now = time.time()
    network_failures = 0
    for model in models:
        for attempt in range(2):
            try:
                r = requests.post(f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=llm_request_payload(name, model, prompt), timeout=LLM_REQUEST_TIMEOUT_SECONDS)
                status = r.status_code
                try:
                    data = r.json()
                except Exception:
                    data = None
                if data and "choices" in data and data["choices"]:
                    content = (data["choices"][0].get("message") or {}).get("content")
                    if content:
                        logger.info(f"LLM working: {model}")
                        return content.strip(), model
                    logger.warning(f"LLM {model} returned empty content; trying next")
                    break
                logger.error(f"LLM error on {model}: HTTP {status} body: {r.text[:300]}")
                if status == 404:
                    llm_disabled_models.add(model)
                    logger.warning(f"Disabling {model} for this session (HTTP 404)")
                    break
                elif status == 429:
                    llm_model_cooldowns[model] = time.time() + 60
                    network_failures += 1
                    if attempt == 0:
                        logger.warning(f"LLM {model} rate limited; retrying after 5s")
                        time.sleep(5)
                        continue
                elif status >= 500:
                    llm_model_cooldowns[model] = time.time() + LLM_FAILURE_MODEL_COOLDOWN_SECONDS
                    network_failures += 1
                    if attempt == 0:
                        logger.warning(f"LLM {model} server error; retrying after 3s")
                        time.sleep(3)
                        continue
                break
            except requests.exceptions.Timeout:
                logger.error(f"LLM timeout on {model}")
                llm_model_cooldowns[model] = time.time() + LLM_TIMEOUT_MODEL_COOLDOWN_SECONDS
                network_failures += 1
                if attempt == 0:
                    logger.warning(f"Retrying {model} after timeout")
                    time.sleep(2)
                    continue
                break
            except Exception as e:
                logger.error(f"LLM error on {model}: {e}")
                network_failures += 1
                if attempt == 0:
                    logger.warning(f"Retrying {model} after error")
                    time.sleep(2)
                    continue
                break
    return None, None

def ask_llm(prompt):
    global llm_cooldown_until, llm_model_cooldowns, LLM_MODEL, VIRTUALS_MODEL, TOKENROUTER_MODEL
    now = time.time()
    if now < llm_cooldown_until:
        logger.warning("LLM cooldown active; skipping this analysis cycle")
        return None
    provider_configs = [
        ("nvidia", NVIDIA_BASE_URL, NVIDIA_API_KEY, [LLM_MODEL] + LLM_FALLBACK_MODELS),
        ("virtuals", VIRTUALS_BASE_URL, VIRTUALS_API_KEY, [VIRTUALS_MODEL] + VIRTUALS_FALLBACK_MODELS),
        ("tokenrouter", TOKENROUTER_BASE_URL, TOKENROUTER_API_KEY, [TOKENROUTER_MODEL] + TOKENROUTER_FALLBACK_MODELS),
    ]
    providers = sorted(
        provider_configs,
        key=lambda p: 0 if p[0] == LLM_PROVIDER else 1,
    )
    attempted = False
    for name, base_url, api_key, model_list in providers:
        if not api_key:
            continue
        models = []
        for model in model_list:
            if model in models or model in llm_disabled_models:
                continue
            if model in llm_model_cooldowns and now < llm_model_cooldowns[model]:
                continue
            models.append(model)
        if not models:
            continue
        attempted = True
        logger.info(f"Trying {name.upper()} provider ({len(models)} model(s))")
        result, working_model = _try_llm_provider(prompt, name, base_url, api_key, models)
        if result:
            if name == "virtuals" and working_model != VIRTUALS_MODEL:
                logger.info(f"Virtuals fallback working: {working_model}")
                VIRTUALS_MODEL = working_model
            elif name == "tokenrouter" and working_model != TOKENROUTER_MODEL:
                logger.info(f"TokenRouter fallback working: {working_model}")
                TOKENROUTER_MODEL = working_model
            elif name == "nvidia" and working_model != LLM_MODEL:
                logger.info(f"NVIDIA fallback working: {working_model}")
                LLM_MODEL = working_model
            return result
        logger.warning(f"{name.upper()} provider failed; trying next")
    if attempted:
        llm_cooldown_until = now + LLM_ERROR_COOLDOWN_SECONDS
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
        # learn from both sides. Normal mode can still skip a side downstream
        # when recent data shows it is decisively losing.
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
            "reason": "Fallback watch-only momentum signal because no LLM provider returned a usable response.",
            "price": price,
        })
    return signals

def extract_json_array(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    candidates = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[", text):
        fragment = text[match.start():]
        try:
            parsed, end = decoder.raw_decode(fragment)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start:end + 1])
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(fenced)
    last_error = None
    for raw in candidates:
        cleaned = raw.strip()
        attempts = [
            cleaned,
            re.sub(r",\s*([}\]])", r"\1", cleaned),
            re.sub(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', re.sub(r",\s*([}\]])", r"\1", cleaned)),
        ]
        for candidate in attempts:
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, list) else []
            except Exception as e:
                last_error = e
            try:
                parsed = ast.literal_eval(candidate)
                return parsed if isinstance(parsed, list) else []
            except Exception as e:
                last_error = e
    logger.error(f"Signal parse error: {last_error}")
    return []

def analyze_top_signals(tickers, balance, force_open=False):
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
    max_open_signals = FORCE_TRADE_ORDERS_PER_COMMAND if force_open else MAX_ORDERS_PER_CYCLE
    force_mode_rules = ""
    if force_open:
        force_mode_rules = f"""

FORCE TRADE MODE:
- The user explicitly requested an order. Learning history, blacklist, cooldown, negative EV, and OPEN false preferences are advisory only.
- Do not avoid a pair or LONG/SHORT side solely because learning context says blocked, weak, blacklisted, or on cooldown.
- Pick the best current market setup from the ranked list and mark OPEN true for up to {FORCE_TRADE_ORDERS_PER_COMMAND} technically possible candidate.
- Still keep leverage/order sizing realistic for the available balance and Bitget minimum notional.
"""
    prompt = f"""You are controlling a Bitget USDT futures bot with about ${balance:.4f} available balance.

Rank these {len(market_rows)} tickers and select the best {TOP_SIGNAL_COUNT} signals.
From those {TOP_SIGNAL_COUNT}, choose at most {max_open_signals} that is worth opening now.
This bot is running in {style_hint} mode.
{force_mode_rules}

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
8. If one direction has weak win rate AND non-positive average net PnL in recent trades, require stronger evidence before opening that direction. If a direction is on loss-streak cooldown (see context), do NOT open that side unless FORCE TRADE MODE is active.
9. The per-pair and side history shown above is net of fees. A pair or specific side with avg PnL near zero or negative over multiple trades is a fee-eating churn.
10. Prefer pairs with clearly positive recent avg net PnL on the exact LONG/SHORT side you propose.
11. Mark OPEN YES for at most {max_open_signals} pairs. If no candidate has clear edge, return them with OPEN false rather than forcing a trade, unless FORCE TRADE MODE is active.
12. Profitability target: only mark OPEN true when the setup is good enough to plausibly win about {AUTO_OPEN_TARGET_WIN_RATE:.0f}% of similar trades after fees. Skip marginal setups even if they are ranked highly.
13. OPEN true should usually have confidence >= {AUTO_OPEN_CONFIDENCE_SCALPING if TRADE_MODE == "scalping" else AUTO_OPEN_CONFIDENCE_NORMAL}. Lower confidence is for WATCH only.
14. Set tp_price and sl_price based on your own analysis. tp_price is the take-profit exit price, sl_price is the stop-loss exit price. These must be on the correct side of entry (tp above entry for LONG, below for SHORT; sl below entry for LONG, above for SHORT).

Respond ONLY valid JSON:
[
  {{"rank":1,"symbol":"BTCUSDT","direction":"LONG","confidence":84,"leverage":4,"margin_usdt":1.4,"size":0.00006,"possible":true,"open":true,"tp_price":67500.0,"sl_price":65000.0,"reason":"brief"}},
  ...
]
"""
    response = ask_llm(prompt)
    if not response:
        logger.warning("Using fallback signal ranking because LLM returned no response")
        return analyze_top_signals_fallback(tickers, balance)
    logger.info(f"LLM raw response (first 800): {response[:800]}")
    logger.info(f"Response type={type(response).__name__}, len={len(response)}, first_char_ord={ord(response[0]) if response else -1}, last_5_chars={repr(response[-5:])}")
    # Direct JSON parse test
    try:
        direct = json.loads(response)
        logger.info(f"Direct json.loads OK: type={type(direct).__name__}, len={len(direct) if isinstance(direct, (list,dict)) else 'N/A'}")
    except Exception as e:
        logger.error(f"Direct json.loads failed: {e}")
    try:
        d = json.JSONDecoder()
        p, e = d.raw_decode(response)
        logger.info(f"raw_decode OK: type={type(p).__name__}, end={e}")
    except Exception as e:
        logger.error(f"raw_decode failed: {e}")
    raw_signals = extract_json_array(response)
    signals = []
    for item in raw_signals:
        if not isinstance(item, dict):
            continue
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
            "tp_price": parse_float(item.get("tp_price"), 0.0),
            "sl_price": parse_float(item.get("sl_price"), 0.0),
        }
        signals.append(signal)
        if len(signals) >= TOP_SIGNAL_COUNT: break
    return signals

def send_top_signals(signals, balance, open_count, force=False):
    if not signals:
        if force:
            send_telegram("❌ <b>No valid signals</b>\nLLM returned no valid signals or parsing failed. Check logs.")
        logger.info("No valid signals returned this cycle.")
        return
    lines = [f"📊 <b>Top {len(signals)} signals</b>\nBalance: <b>{balance:.4f} USDT</b>\nOpen positions: <b>{open_count}/{MAX_POSITIONS}</b>"]
    for s in signals:
        possible = "OK" if s["possible"] else "NO"
        open_mark = "OPEN" if s["open"] else "WATCH"
        tp_str = f" TP: {s['tp_price']}" if s.get('tp_price') else ""
        sl_str = f" SL: {s['sl_price']}" if s.get('sl_price') else ""
        lines.append(
            f"{s['rank']}. <b>{s['symbol']}</b> {s['direction']} | Conf: <b>{s['confidence']}%</b> | "
            f"Lev: <b>{s['leverage']}x</b> | Margin: <b>{s['margin_usdt']:.4f}</b> | {possible}/{open_mark}"
            f"{tp_str}{sl_str}\n"
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
    margin_fraction = DRY_RUN_TARGET_MARGIN_PER_TRADE_FRACTION if DRY_RUN else MAX_MARGIN_PER_TRADE_FRACTION
    margin_cap = min(balance * margin_fraction, max(0.0, balance - MIN_FREE_BALANCE_USDT))
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

def auto_entry_allowed(signal, symbol, leverage, side_has_edge=False, side_edge_stats=None):
    confidence = parse_int(signal.get("confidence"), 0)
    min_conf = AUTO_OPEN_CONFIDENCE_SCALPING if TRADE_MODE == "scalping" else AUTO_OPEN_CONFIDENCE_NORMAL
    recent_stats = get_recent_trade_stats()
    if (
        recent_stats["total"] >= RECENT_PROFIT_MIN_TRADES
        and (recent_stats["avg_pnl"] <= 0 or recent_stats["win_rate"] < RECENT_PROFIT_MIN_WIN_RATE)
    ):
        min_conf += RECENT_DEFENSE_CONFIDENCE_BONUS
    if confidence < min_conf:
        return False, f"confidence {confidence}% below auto-open threshold {min_conf}%"
    rr = TAKE_PROFIT_ROI_PCT / max(STOP_LOSS_ROI_PCT, 0.01)
    if rr < MIN_REWARD_RISK_RATIO:
        return False, f"reward/risk {rr:.2f} below {MIN_REWARD_RISK_RATIO:.2f}"
    if leverage > PROFIT_GUARD_MAX_LEVERAGE and confidence < PROFIT_GUARD_MAX_LEVERAGE_CONFIDENCE:
        return False, f"leverage {leverage}x requires confidence >= {PROFIT_GUARD_MAX_LEVERAGE_CONFIDENCE}%"

    pair_stats = get_pair_recent_stats(symbol)
    side_stats = side_edge_stats or get_pair_direction_recent_stats(symbol, signal["direction"])
    if pair_stats["total"] == 0 and side_stats["total"] == 0 and confidence < PROFIT_GUARD_UNKNOWN_HISTORY_CONFIDENCE:
        return False, f"no pair/side history; requires confidence >= {PROFIT_GUARD_UNKNOWN_HISTORY_CONFIDENCE}%"
    if side_stats["total"] > 0 and side_stats["avg_pnl"] <= 0 and not side_has_edge:
        return False, f"{signal['direction']} side avg net PnL {side_stats['avg_pnl']:+.4f} is not positive"
    if pair_stats["total"] >= PAIR_NEGATIVE_EV_MIN_TRADES:
        if pair_stats["avg_pnl"] <= 0 and not side_has_edge:
            return False, f"pair avg net PnL {pair_stats['avg_pnl']:+.4f} is not positive"
        if pair_stats["win_rate"] < PROFIT_GUARD_PAIR_MIN_WIN_RATE and not side_has_edge:
            return False, f"pair win rate {pair_stats['win_rate']:.0f}% below {PROFIT_GUARD_PAIR_MIN_WIN_RATE:.0f}%"
    if side_stats["total"] >= PROFIT_GUARD_SIDE_MIN_TRADES:
        if side_stats["avg_pnl"] <= 0:
            return False, f"{signal['direction']} side avg net PnL {side_stats['avg_pnl']:+.4f} is not positive"
        if side_stats["win_rate"] < PROFIT_GUARD_SIDE_MIN_WIN_RATE:
            return False, f"{signal['direction']} side win rate {side_stats['win_rate']:.0f}% below {PROFIT_GUARD_SIDE_MIN_WIN_RATE:.0f}%"
    return True, ""

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
    hold_side = normalize_hold_side(hold_side)
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
    current_price = parse_float(position.get("markPrice", entry_price), entry_price)
    leverage = max(1, parse_int(position.get("leverage"), MIN_LEVERAGE))
    size = get_position_size_value(position)
    hold_side = normalize_hold_side(position.get("holdSide", "long"))
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
    hold_side = normalize_hold_side(position.get("holdSide", "long"))
    size = get_position_size_value(position)
    if entry_price <= 0 or current_price <= 0 or size <= 0:
        return 0.0, 0.0, 0.0, current_price, size
    net_pnl, fee = calculate_net_pnl(entry_price, current_price, size, hold_side)
    return net_pnl, fee, size, current_price, entry_price

def find_and_trade():
    global last_trade_time, force_trade, force_open_trade, daily_loss_locked_date, consecutive_loss_cooldown_until
    force_open_requested = force_open_trade
    force_trade_requested = force_trade
    force_trade = False
    force_open_trade = False
    positions = get_auto_strategy_positions()
    balance = get_strategy_balance()
    today_net_pnl = get_strategy_today_net_pnl()
    today = datetime.now().strftime("%Y-%m-%d")
    if today_net_pnl <= -MAX_DAILY_LOSS_USD:
        if force_open_requested:
            logger.warning(f"Force trade overriding daily loss limit: {today_net_pnl:.4f}/-{MAX_DAILY_LOSS_USD:.4f}")
        else:
            if daily_loss_locked_date != today:
                send_telegram(f"🛑 <b>Daily loss limit reached</b>\nNet PnL: <b>{today_net_pnl:.4f} USDT</b>\nLimit: <b>-{MAX_DAILY_LOSS_USD:.4f} USDT</b>\nNew entries paused for today.")
                daily_loss_locked_date = today
            logger.info(f"Daily loss limit reached: {today_net_pnl:.4f}/-{MAX_DAILY_LOSS_USD:.4f}; entries paused")
            force_trade = False
            force_open_trade = False
            return
    if time.time() < consecutive_loss_cooldown_until:
        remaining = int((consecutive_loss_cooldown_until - time.time()) / 60) + 1
        if force_open_requested:
            logger.warning(f"Force trade overriding consecutive loss cooldown ({remaining} min left)")
        else:
            logger.info(f"Consecutive loss cooldown active ({remaining} min left); skipping new entries")
            force_trade = False
            force_open_trade = False
            return
    if not force_trade_requested and last_trade_time and time.time() - last_trade_time < TRADE_COOLDOWN_MIN * 60:
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
        force_open_trade = False
        return
    logger.info(f"Analyzing {len(candidates)} tickers...")
    update_blacklist()
    check_and_apply_loss_streak_cooldowns()
    signals = analyze_top_signals(candidates, balance, force_open_requested)
    if force_open_requested:
        send_top_signals(signals, balance, len(positions), force=True)
    else:
        maybe_send_top_signals(signals, balance, len(positions))
    if len(positions) >= MAX_POSITIONS:
        logger.info(f"Max positions reached: {len(positions)}/{MAX_POSITIONS}; signals only")
        if force_open_requested:
            send_telegram(f"⚠️ <b>Force trade skipped</b>\nAuto positions already full: <b>{len(positions)}/{MAX_POSITIONS}</b>.")
        return
    ticker_map = {t["symbol"]: t for t in candidates}
    existing_symbols = {p["symbol"] for p in positions}
    preferred = [s for s in signals if s["open"]]
    order_candidates = signals if force_open_requested else preferred
    opened = 0
    max_per_run = FORCE_TRADE_ORDERS_PER_COMMAND if force_open_requested else MAX_ORDERS_PER_CYCLE
    max_to_open = min(max_per_run, MAX_POSITIONS - len(positions))
    for signal in order_candidates:
        if opened >= max_to_open: break
        symbol = signal["symbol"]
        if symbol in existing_symbols: continue
        side_has_edge, side_edge_stats = pair_direction_has_edge(symbol, signal["direction"])
        if force_open_requested:
            logger.warning(f"Force trade bypassing strategy filters for {symbol} {signal['direction']}")
        elif symbol in blacklisted_pairs and not side_has_edge:
            logger.info(f"Skipping {symbol} - blacklisted (loss rate >= {BLACKLIST_LOSS_RATE_PCT:.0f}%)")
            continue
        if not force_open_requested and direction_cooldown_active(signal["direction"]):
            logger.info(f"Skipping {symbol} {signal['direction']} - direction loss-streak cooldown active")
            continue
        if not force_open_requested and not direction_allowed(signal["direction"]) and not side_has_edge:
            logger.info(f"Skipping {symbol} {signal['direction']} - direction blocked by recent performance / cooldown")
            continue
        if not force_open_requested and side_has_edge and not direction_allowed(signal["direction"]):
            logger.info(f"Allowing {symbol} {signal['direction']} despite global direction block - pair+side edge (last {side_edge_stats['total']}: avg {side_edge_stats['avg_pnl']:+.4f} USDT, WR {side_edge_stats['win_rate']:.0f}%)")
        bad_side_ev, side_stats = pair_direction_negative_ev(symbol, signal["direction"])
        if not force_open_requested and bad_side_ev:
            logger.info(f"Skipping {symbol} {signal['direction']} - weak pair+side history (last {side_stats['total']}: avg {side_stats['avg_pnl']:+.4f} USDT, WR {side_stats['win_rate']:.0f}%)")
            continue
        bad_ev, ev_stats = pair_negative_ev(symbol)
        if not force_open_requested and bad_ev and not side_has_edge:
            logger.info(f"Skipping {symbol} - negative EV (last {ev_stats['total']}: avg {ev_stats['avg_pnl']:+.4f} USDT, WR {ev_stats['win_rate']:.0f}%)")
            continue
        loss_streak, loss_streak_reason = pair_loss_streak_active(symbol)
        if not force_open_requested and loss_streak:
            logger.info(f"Skipping {symbol} - pair cooldown ({loss_streak_reason})")
            continue
        if not force_open_requested and (signal["confidence"] < MIN_CONFIDENCE or not signal["possible"]): continue
        price = parse_float(ticker_map.get(symbol, {}).get("lastPr"), signal.get("price", 0.0))
        size, margin, leverage = calculate_position_size(balance, signal, price)
        notional = size * price
        if price <= 0 or size <= 0 or margin <= 0 or margin > balance or notional < MIN_NOTIONAL:
            logger.info(f"Skipping {symbol} - cannot meet minimum with balance/leverage")
            continue
        if not force_open_requested:
            allowed, guard_reason = auto_entry_allowed(signal, symbol, leverage, side_has_edge, side_edge_stats)
            if not allowed:
                logger.info(f"Skipping {symbol} {signal['direction']} - profit guard: {guard_reason}")
                continue
        decision, confidence, reasoning = signal["direction"], signal["confidence"], signal["reason"]
        hold_side = "long" if decision == "LONG" else "short"
        side = "buy" if decision == "LONG" else "sell"
        tp_price = signal.get("tp_price", 0.0)
        sl_price = signal.get("sl_price", 0.0)
        if not LLM_MANAGE_ENTRY or tp_price <= 0 or sl_price <= 0:
            tp_price, sl_price = calculate_roi_prices(price, hold_side, leverage)
        if DRY_RUN:
            dry_action = f"DRY_{decision}"
            save_trade_open(symbol, dry_action, price, size, leverage, confidence)
            last_trade_time = time.time()
            tp_roi = ((tp_price - price) / price * 100 * leverage) if hold_side == "long" and price > 0 else ((price - tp_price) / price * 100 * leverage) if price > 0 else 0
            sl_roi = ((price - sl_price) / price * 100 * leverage) if hold_side == "long" and price > 0 else ((sl_price - price) / price * 100 * leverage) if price > 0 else 0
            msg = (f"🧪 <b>DRY RUN {decision} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
                   f"Size: <b>{size}</b> | Margin: <b>{margin:.4f} USDT</b> | Notional: <b>{notional:.2f} USDT</b>\n"
                   f"Leverage: <b>{leverage}x</b>\nConfidence: <b>{confidence}%</b>\n"
                   f"TP: <b>{tp_roi:+.2f}%</b> @ <b>{tp_price}</b>\n"
                   f"SL: <b>{sl_roi:+.2f}%</b> @ <b>{sl_price}</b>\n"
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
            tp_roi = ((tp_price - price) / price * 100 * leverage) if hold_side == "long" and price > 0 else ((price - tp_price) / price * 100 * leverage) if price > 0 else 0
            sl_roi = ((price - sl_price) / price * 100 * leverage) if hold_side == "long" and price > 0 else ((sl_price - price) / price * 100 * leverage) if price > 0 else 0
            msg = (f"🟢 <b>{decision} OPENED</b>\nSymbol: <b>{symbol}</b>\nEntry: <b>{price:.6f}</b>\n"
                   f"Size: <b>{size}</b> | Margin: <b>{margin:.4f} USDT</b> | Notional: <b>{notional:.2f} USDT</b>\n"
                   f"Leverage: <b>{leverage}x</b>\nConfidence: <b>{confidence}%</b>\n"
                   f"TP: <b>{tp_roi:+.2f}%</b> @ <b>{tp_price}</b>\n"
                   f"SL: <b>{sl_roi:+.2f}%</b> @ <b>{sl_price}</b>\n\n💡 {reasoning}")
            send_telegram(msg)
            logger.info(f"Opened {decision} {symbol} @ {price} | Size: {size} | Lev: {leverage}x")
            opened += 1
            existing_symbols.add(symbol)
        else:
            logger.error(f"Order failed for {symbol}: {res.get('msg')}")
    if opened == 0:
        logger.info("No orders opened this cycle")
        if force_open_requested:
            send_telegram("⚠️ <b>Force trade did not open an order</b>\nAll Top 10 candidates failed hard limits: max positions, duplicate pair, balance, leverage setup, or minimum order sizing.")

def sleep_until_next_cycle(seconds):
    end_at = time.time() + seconds
    while bot_running and time.time() < end_at:
        if force_trade:
            return
        time.sleep(min(1, max(0, end_at - time.time())))

def manage_positions():
    global consecutive_losses, consecutive_loss_cooldown_until
    positions = get_strategy_positions()
    if not positions: return
    for p in positions:
        symbol = p["symbol"]
        hold_side = normalize_hold_side(p.get("holdSide", "long"))
        p["holdSide"] = hold_side
        entry = parse_float(p.get("openPriceAvg", 0), 0.0)
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
            current = parse_float(p.get("markPrice", 0), 0.0)
            net_pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
            pnl = net_pnl if size > 0 else parse_float(p.get("unrealizedPL", 0), 0.0)
        roi_pct = calculate_position_roi_pct(p)
        if roi_pct >= TAKE_PROFIT_ROI_PCT:
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            ok, close_reason = close_position_succeeded(res, symbol, hold_side)
            if ok:
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                clear_trailing_stop(symbol, hold_side)
                consecutive_losses = 0
                prefix = "DRY RUN " if DRY_RUN else ""
                send_telegram(f"✅ <b>{prefix}TAKE PROFIT</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nNet ROI: <b>+{roi_pct:.2f}%</b>\nNet PnL: <b>+{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                logger.info(f"{prefix}TP hit {symbol} | Net ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f} | Fee: {fee:.4f}")
                continue
            logger.error(f"TP close failed for {hold_side} {symbol}: {close_reason} | response={json.dumps(res, ensure_ascii=False)}")
        if check_stop_loss(p, entry):
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            ok, close_reason = close_position_succeeded(res, symbol, hold_side)
            if ok:
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
            logger.error(f"SL close failed for {hold_side} {symbol}: {close_reason} | response={json.dumps(res, ensure_ascii=False)}")
        if check_trailing_stop(trail_key, roi_pct):
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            ok, close_reason = close_position_succeeded(res, symbol, hold_side)
            if ok:
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                peak = trailing_stops.pop(trail_key, roi_pct)
                trailing_stops.pop(symbol, None)
                if pnl <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                    consecutive_loss_cooldown_until = time.time() + CONSECUTIVE_LOSS_COOLDOWN_MIN * 60
                    send_telegram(f"⏸️ <b>Cooldown</b>\nReached {consecutive_losses} consecutive losses (limit {CONSECUTIVE_LOSS_LIMIT}).\nNew entries paused for <b>{CONSECUTIVE_LOSS_COOLDOWN_MIN} min</b>.")
                    logger.warning(f"Consecutive loss limit hit ({consecutive_losses}); cooldown {CONSECUTIVE_LOSS_COOLDOWN_MIN} min")
                    consecutive_losses = 0
                prefix = "DRY RUN " if DRY_RUN else ""
                emoji = "🔻" if pnl <= 0 else "✅"
                send_telegram(f"{emoji} <b>{prefix}TRAILING STOP</b>\n{hold_side.upper()} {symbol}\nEntry: {entry:.6f} → Exit: {current:.6f}\nPeak ROI: <b>+{peak:.2f}%</b> → Now: <b>{roi_pct:.2f}%</b>\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                logger.info(f"{prefix}Trailing stop hit {symbol} | Peak ROI: {peak:.2f}% | Exit ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f}")
                continue
            logger.error(f"Trailing close failed for {hold_side} {symbol}: {close_reason} | response={json.dumps(res, ensure_ascii=False)}")
        age_hours = position_age_hours(p)
        if MAX_HOLD_HOURS > 0 and age_hours >= MAX_HOLD_HOURS:
            res = {"code": "00000"} if DRY_RUN else close_position_api(symbol, hold_side)
            ok, close_reason = close_position_succeeded(res, symbol, hold_side)
            if ok:
                save_trade_close_by_id(p["id"], current, pnl) if DRY_RUN else save_trade_close(symbol, current, pnl, hold_side)
                clear_trailing_stop(symbol, hold_side)
                if pnl <= 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                    consecutive_loss_cooldown_until = time.time() + CONSECUTIVE_LOSS_COOLDOWN_MIN * 60
                    send_telegram(f"⏸️ <b>Cooldown</b>\nReached {consecutive_losses} consecutive losses (limit {CONSECUTIVE_LOSS_LIMIT}).\nNew entries paused for <b>{CONSECUTIVE_LOSS_COOLDOWN_MIN} min</b>.")
                    logger.warning(f"Consecutive loss limit hit ({consecutive_losses}); cooldown {CONSECUTIVE_LOSS_COOLDOWN_MIN} min")
                    consecutive_losses = 0
                prefix = "DRY RUN " if DRY_RUN else ""
                emoji = "⏱️" if pnl >= 0 else "⏱️🔻"
                send_telegram(f"{emoji} <b>{prefix}TIME STOP</b>\n{hold_side.upper()} {symbol}\nHeld: <b>{age_hours:.1f}h</b> (limit {MAX_HOLD_HOURS}h)\nEntry: {entry:.6f} → Exit: {current:.6f}\nNet ROI: <b>{roi_pct:.2f}%</b>\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                logger.info(f"{prefix}Time stop {symbol} | Age: {age_hours:.1f}h | Net ROI: {roi_pct:.2f}% | Net PnL: {pnl:.4f}")
                continue
            logger.error(f"Time-stop close failed for {hold_side} {symbol}: {close_reason} | response={json.dumps(res, ensure_ascii=False)}")

def handle_status(chat_id):
    positions, auto_positions, manual_count = get_position_counts()
    balance, daily_pnl = get_strategy_balance(), get_strategy_today_net_pnl()
    real_balance = get_balance() if DRY_RUN else balance
    mode = f"{'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}"
    if not positions:
        send_telegram_buttons(f"📊 <b>Status</b>\nMode: <b>{mode}</b>\nBalance: <b>{balance:.4f} USDT</b>\nReal balance: <b>{real_balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nAuto positions: <b>0/{MAX_POSITIONS}</b>\nManual positions: <b>0</b>\nConsecutive losses: <b>{consecutive_losses}</b>", [[("🔙 Menu", "menu:main")]], chat_id)
        return
    lines = [f"📊 <b>Status</b>\nMode: <b>{mode}</b>\nBalance: <b>{balance:.4f} USDT</b>\nReal balance: <b>{real_balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nAuto positions: <b>{len(auto_positions)}/{MAX_POSITIONS}</b>\nManual positions: <b>{manual_count}</b>\nConsecutive losses: <b>{consecutive_losses}</b>\n"]
    for p in positions:
        entry = parse_float(p.get("openPriceAvg", 0), 0.0)
        hold_side = normalize_hold_side(p.get("holdSide", "long"))
        if DRY_RUN:
            ticker = next((t for t in get_tickers() if t.get("symbol") == p["symbol"]), {})
            current = parse_float(ticker.get("lastPr"), entry)
            pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
        else:
            current = parse_float(p.get("markPrice", 0), 0.0)
            pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
        emoji = "🟢" if pnl > 0 else "🔴"
        pnl_pct = 0.0 if entry <= 0 else (((current - entry) / entry * 100) if hold_side == "long" else ((entry - current) / entry * 100))
        lines.append(f"{emoji} {hold_side.upper()} {p['symbol']}\nEntry: {entry:.6f} | Now: {current:.6f}\nNet PnL: <b>{pnl:.4f} USDT ({pnl_pct:+.2f}%)</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
    lines.append("")
    send_telegram_buttons("\n\n".join(lines), [[("🔙 Menu", "menu:main")]], chat_id)

def handle_balance(chat_id):
    balance, daily_pnl = get_strategy_balance(), get_strategy_today_net_pnl()
    real_balance = get_balance() if DRY_RUN else balance
    mode = f"{'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}"
    send_telegram_buttons(f"💰 <b>Balance</b>\nMode: <b>{mode}</b>\nAvailable: <b>{balance:.4f} USDT</b>\nReal balance: <b>{real_balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nMax daily loss: <b>{MAX_DAILY_LOSS_USD} USDT</b>", [[("🔙 Menu", "menu:main")]], chat_id)

def handle_history(chat_id):
    summary = get_trade_summary()
    if not summary:
        send_telegram_buttons("📈 Belum ada trade history.", [[("🔙 Menu", "menu:main")]], chat_id)
    else:
        send_telegram_buttons(f"📈 <b>Trade History</b>\n\nTotal trades: <b>{summary['total_trades']}</b>\nWin rate: <b>{summary['win_rate']}</b>\nAvg PnL: <b>{summary['avg_pnl']} USDT</b>\nBest pair: <b>{summary['best_pair']}</b>\nWorst pair: <b>{summary['worst_pair']}</b>\n\n<b>Last 10 Trades:</b>\n{summary['last_10']}", [[("🔙 Menu", "menu:main")]], chat_id)

def handle_commands():
    global bot_running, force_trade, force_open_trade, consecutive_losses, consecutive_loss_cooldown_until, LLM_MODEL, VIRTUALS_MODEL, TOKENROUTER_MODEL, LLM_PROVIDER, DRY_RUN, LLM_MANAGE_ENTRY
    logger.info("Telegram handler started")
    while bot_running:
        try:
            updates = get_telegram_updates()
            for u in updates:
                cb = u.get("callback_query")
                if cb:
                    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", ""))
                    if chat_id not in TELEGRAM_CHAT_IDS:
                        continue
                    cb_data = cb.get("data", "")
                    cb_id = cb.get("id", "")
                    msg_id = cb.get("message", {}).get("message_id")
                    if cb_data.startswith("mdl:"):
                        parts = cb_data.split(":")
                        if len(parts) == 3:
                            _, prov, idx_str = parts
                            idx = int(idx_str)
                            provider = LLM_PROVIDER_BY_CODE.get(prov, "nvidia")
                            if provider == "nvidia":
                                all_m = provider_model_list(provider)
                                if 0 <= idx < len(all_m):
                                    new_m = all_m[idx]
                                    if new_m != LLM_MODEL:
                                        LLM_MODEL = new_m
                                        logger.info(f"Model changed to {LLM_MODEL}")
                            elif provider == "virtuals":
                                all_m = provider_model_list(provider)
                                if 0 <= idx < len(all_m):
                                    new_m = all_m[idx]
                                    if new_m != VIRTUALS_MODEL:
                                        VIRTUALS_MODEL = new_m
                                        logger.info(f"Virtuals model changed to {VIRTUALS_MODEL}")
                            elif provider == "tokenrouter":
                                all_m = provider_model_list(provider)
                                if 0 <= idx < len(all_m):
                                    new_m = all_m[idx]
                                    if new_m != TOKENROUTER_MODEL:
                                        TOKENROUTER_MODEL = new_m
                                        logger.info(f"TokenRouter model changed to {TOKENROUTER_MODEL}")
                        edit_message_buttons(chat_id, msg_id, f"🧠 Model ({LLM_PROVIDER_LABELS[LLM_PROVIDER]})\nCurrent: <code>{active_llm_model()}</code>", [[("🔙 Menu", "menu:main")]])
                        answer_callback(cb_id)
                        continue
                    if cb_data == "menu:main":
                        edit_message_buttons(chat_id, msg_id, "🤖 <b>Bitget LLM Bot</b>\nPilih menu:", main_menu())
                        answer_callback(cb_id)
                        continue
                    if cb_data == "menu:status":
                        answer_callback(cb_id)
                        handle_status(chat_id)
                        continue
                    if cb_data == "menu:balance":
                        answer_callback(cb_id)
                        handle_balance(chat_id)
                        continue
                    if cb_data == "menu:history":
                        answer_callback(cb_id)
                        handle_history(chat_id)
                        continue
                    if cb_data == "menu:trade":
                        force_trade = True
                        consecutive_losses = 0
                        consecutive_loss_cooldown_until = 0
                        answer_callback(cb_id, "⚡ Scanning...")
                        send_telegram("⚡ Starting analysis...")
                        continue
                    if cb_data == "menu:forcetrade":
                        force_trade = True
                        force_open_trade = True
                        consecutive_losses = 0
                        consecutive_loss_cooldown_until = 0
                        answer_callback(cb_id, "⚡ Force trade...")
                        send_telegram(f"⚡ <b>Force trade requested</b>\nBypassing filters/cooldowns.")
                        continue
                    if cb_data == "menu:model":
                        answer_callback(cb_id)
                        all_m = provider_model_list(LLM_PROVIDER)
                        primary = provider_primary_model(LLM_PROVIDER)
                        prov = LLM_PROVIDER_CODES[LLM_PROVIDER]
                        btns = []
                        for i, m in enumerate(all_m):
                            active = " ✅" if m == primary else ""
                            short = m.split("/")[-1].split("-")[0] if "/" in m else m.split("-")[0]
                            btns.append([(f"{i+1}. {short}{active}", f"mdl:{prov}:{i}")])
                        btns.append([("🔙 Menu", "menu:main")])
                        edit_message_buttons(chat_id, msg_id, f"🧠 <b>Model ({LLM_PROVIDER_LABELS[LLM_PROVIDER]})</b>\nCurrent: <code>{primary}</code>", btns)
                        continue
                    if cb_data == "menu:provider":
                        answer_callback(cb_id)
                        edit_message_buttons(chat_id, msg_id, f"🔌 <b>LLM Provider</b>\nCurrent: <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>", provider_button_rows())
                        continue
                    if cb_data == "menu:paper":
                        answer_callback(cb_id)
                        active = "dry" if DRY_RUN else "live"
                        btns = [
                            [("📄 PAPER ✅" if active == "dry" else "📄 PAPER", "paper:dry")],
                            [("💰 LIVE ✅" if active == "live" else "💰 LIVE", "paper:live")],
                            [("🔙 Menu", "menu:main")],
                        ]
                        edit_message_buttons(chat_id, msg_id, f"📄 <b>Trade Mode</b>\nCurrent: <b>{'PAPER (DRY RUN)' if DRY_RUN else 'LIVE'}</b>", btns)
                        continue
                    if cb_data == "menu:mode":
                        answer_callback(cb_id)
                        active = TRADE_MODE
                        btns = [
                            [("⚡ Scalping ✅" if active == "scalping" else "⚡ Scalping", "mode:scalping")],
                            [("📊 Normal ✅" if active == "normal" else "📊 Normal", "mode:normal")],
                            [("🔙 Menu", "menu:main")],
                        ]
                        edit_message_buttons(chat_id, msg_id, f"⚙️ <b>Trading Mode</b>\nCurrent: <b>{active.upper()}</b>", btns)
                        continue
                    if cb_data == "menu:entrymode":
                        LLM_MANAGE_ENTRY = not LLM_MANAGE_ENTRY
                        logger.info(f"LLM entry mode toggled to {'autopilot' if LLM_MANAGE_ENTRY else 'manual TP/SL'}")
                        answer_callback(cb_id, f"Auto TP/SL: {'ON' if LLM_MANAGE_ENTRY else 'OFF'}")
                        label = "🤖 Auto TP/SL ✅" if LLM_MANAGE_ENTRY else "🤖 Auto TP/SL ❌"
                        edit_message_buttons(chat_id, msg_id, f"🤖 <b>Entry Mode</b>\nCurrent: <b>{'Autopilot (LLM sets TP/SL)' if LLM_MANAGE_ENTRY else 'Manual (bot calculates TP/SL)'}</b>", [
                            [(label, "menu:entrymode")],
                            [("🔙 Menu", "menu:main")],
                        ])
                        continue
                    if cb_data == "menu:stop":
                        answer_callback(cb_id, "🛑 Stopping bot...")
                        send_telegram("🛑 Bot stopped.")
                        bot_running = False
                        continue
                    if cb_data == "menu:help":
                        answer_callback(cb_id)
                        msg = (
                            f"📋 <b>Menu Bantuan</b>\n\n"
                            f"📊 <b>Status</b> — lihat posisi + PnL\n"
                            f"💰 <b>Balance</b> — saldo + daily PnL\n"
                            f"📈 <b>History</b> — statistik trading\n"
                            f"⚡ <b>Trade</b> — scan sinyal sekarang\n"
                            f"⚡ <b>Force</b> — paksa buka posisi\n"
                            f"🧠 <b>Model</b> — ganti model LLM\n"
                            f"🔌 <b>Provider</b> — ganti LLM provider\n"
                            f"📄 <b>Paper/Live</b> — ganti mode trading\n"
                            f"⚙️ <b>Mode</b> — scalping / normal\n"
                            f"🤖 <b>Auto TP/SL</b> — LLM atur TP/SL atau manual\n"
                            f"🛑 <b>Stop</b> — matikan bot\n\n"
                            f"<b>Settings:</b>\n"
                            f"Trade: <b>{'PAPER' if DRY_RUN else 'LIVE'}</b>\n"
                            f"Provider: <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>\n"
                            f"Mode: {TRADE_MODE.upper()}\n"
                            f"Auto TP/SL: {'✅' if LLM_MANAGE_ENTRY else '❌'}\n"
                            f"TP: {TAKE_PROFIT_ROI_PCT:.0f}% | SL: {STOP_LOSS_ROI_PCT:.0f}%\n"
                            f"Scan: every {SLEEP_MINUTES} min"
                        )
                        edit_message_buttons(chat_id, msg_id, msg, [[("🔙 Menu", "menu:main")]])
                        continue
                    if cb_data.startswith("prov:"):
                        val = cb_data.split(":")[1]
                        if val not in SUPPORTED_LLM_PROVIDERS:
                            answer_callback(cb_id, "Provider tidak dikenal")
                            continue
                        if val != LLM_PROVIDER:
                            LLM_PROVIDER = val
                            logger.info(f"LLM provider changed to {LLM_PROVIDER}")
                        answer_callback(cb_id, f"Provider: {LLM_PROVIDER_LABELS[val]}")
                        edit_message_buttons(chat_id, msg_id, f"🔌 <b>LLM Provider</b>\nCurrent: <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>", provider_button_rows())
                        continue
                    if cb_data.startswith("paper:"):
                        val = cb_data.split(":")[1]
                        new_val = val == "dry"
                        label = "PAPER (DRY RUN)" if new_val else "LIVE"
                        if new_val != DRY_RUN:
                            DRY_RUN = new_val
                            logger.info(f"Trade mode changed to {'DRY RUN' if DRY_RUN else 'LIVE'}")
                        answer_callback(cb_id, label)
                        edit_message_buttons(chat_id, msg_id, f"📄 <b>Trade Mode</b>\nCurrent: <b>{label}</b>", [
                            [("📄 PAPER ✅" if DRY_RUN else "📄 PAPER", "paper:dry")],
                            [("💰 LIVE ✅" if not DRY_RUN else "💰 LIVE", "paper:live")],
                            [("🔙 Menu", "menu:main")],
                        ])
                        continue
                    if cb_data.startswith("mode:"):
                        val = cb_data.split(":")[1]
                        if val != TRADE_MODE and apply_trade_mode(val):
                            logger.info(f"Trade mode changed to {TRADE_MODE.upper()}")
                        answer_callback(cb_id, f"Mode: {TRADE_MODE.upper()}")
                        active = TRADE_MODE
                        edit_message_buttons(chat_id, msg_id, f"⚙️ <b>Trading Mode</b>\nCurrent: <b>{active.upper()}</b>", [
                            [("⚡ Scalping ✅" if active == "scalping" else "⚡ Scalping", "mode:scalping")],
                            [("📊 Normal ✅" if active == "normal" else "📊 Normal", "mode:normal")],
                            [("🔙 Menu", "menu:main")],
                        ])
                        continue
                    answer_callback(cb_id)
                    continue
                msg, chat_id, text = u.get("message", {}), str(u.get("message", {}).get("chat", {}).get("id", "")), u.get("message", {}).get("text", "").strip().lower()
                if chat_id not in TELEGRAM_CHAT_IDS: continue
                if text in ("/start", "/menu") or not text.startswith("/"):
                    send_telegram_buttons("🤖 <b>Bitget LLM Bot</b>\nPilih menu:", main_menu(), chat_id)
                    continue
                if text == "/status":
                    positions, auto_positions, manual_count = get_position_counts()
                    balance, daily_pnl = get_strategy_balance(), get_strategy_today_net_pnl()
                    real_balance = get_balance() if DRY_RUN else balance
                    mode = f"{'DRY RUN' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}"
                    if not positions:
                        send_telegram(f"📊 <b>Status</b>\nMode: <b>{mode}</b>\nBalance: <b>{balance:.4f} USDT</b>\nReal balance: <b>{real_balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nAuto positions: <b>0/{MAX_POSITIONS}</b>\nManual positions: <b>0</b>\nConsecutive losses: <b>{consecutive_losses}</b>")
                    else:
                        lines = [f"📊 <b>Status</b>\nMode: <b>{mode}</b>\nBalance: <b>{balance:.4f} USDT</b>\nReal balance: <b>{real_balance:.4f} USDT</b>\nDaily PnL: <b>{daily_pnl:.4f} USDT</b>\nAuto positions: <b>{len(auto_positions)}/{MAX_POSITIONS}</b>\nManual positions: <b>{manual_count}</b>\nConsecutive losses: <b>{consecutive_losses}</b>\n"]
                        for p in positions:
                            entry = parse_float(p.get("openPriceAvg", 0), 0.0)
                            hold_side = normalize_hold_side(p.get("holdSide", "long"))
                            if DRY_RUN:
                                ticker = next((t for t in get_tickers() if t.get("symbol") == p["symbol"]), {})
                                current = parse_float(ticker.get("lastPr"), entry)
                                pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
                            else:
                                current = parse_float(p.get("markPrice", 0), 0.0)
                                pnl, fee, size, current, entry = estimate_position_net_pnl(p, current)
                            emoji = "🟢" if pnl > 0 else "🔴"
                            pnl_pct = 0.0 if entry <= 0 else (((current - entry) / entry * 100) if hold_side == "long" else ((entry - current) / entry * 100))
                            lines.append(f"{emoji} {hold_side.upper()} {p['symbol']}\nEntry: {entry:.6f} | Now: {current:.6f}\nNet PnL: <b>{pnl:.4f} USDT ({pnl_pct:+.2f}%)</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
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
                elif text == "/forcetrade":
                    force_trade = True
                    force_open_trade = True
                    consecutive_losses = 0
                    consecutive_loss_cooldown_until = 0
                    send_telegram(f"⚡ <b>Force trade requested</b>\nBypassing learning filters/cooldowns and opening max <b>{FORCE_TRADE_ORDERS_PER_COMMAND}</b> pair if hard order limits allow it. Auto max positions stay <b>{MAX_POSITIONS}</b>.")
                elif text == "/model":
                    all_m = provider_model_list(LLM_PROVIDER)
                    primary = provider_primary_model(LLM_PROVIDER)
                    prov = LLM_PROVIDER_CODES[LLM_PROVIDER]
                    buttons = []
                    for i, m in enumerate(all_m):
                        active = " ✅" if m == primary else ""
                        short = m.split("/")[-1].split("-")[0] if "/" in m else m.split("-")[0]
                        label = f"{i+1}. {short}{active}"
                        buttons.append([(label, f"mdl:{prov}:{i}")])
                    send_telegram_buttons(
                        f"🧠 <b>Model ({LLM_PROVIDER_LABELS[LLM_PROVIDER]})</b>\nCurrent: <code>{primary}</code>",
                        buttons)
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
                elif text.startswith("/provider"):
                    parts = text.split()
                    if len(parts) == 1:
                        available = ", ".join(f"<b>{label}</b>" for label in LLM_PROVIDER_LABELS.values())
                        send_telegram(f"🔌 <b>LLM Provider</b>\nCurrent: <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>\nAvailable: {available}\nUse /provider nvidia, /provider virtuals, atau /provider tokenrouter")
                    else:
                        requested = parts[1].strip().lower()
                        if requested in ("nvidia", "nv"):
                            new_val = "nvidia"
                        elif requested in ("virtuals", "virtual", "vrt"):
                            new_val = "virtuals"
                        elif requested in ("tokenrouter", "token", "router", "tok3nrouter", "tr"):
                            new_val = "tokenrouter"
                        else:
                            send_telegram("⚠️ Provider tidak dikenal. Pilih: /provider nvidia, /provider virtuals, atau /provider tokenrouter")
                            continue
                        if new_val == LLM_PROVIDER:
                            send_telegram(f"✅ Provider sudah <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>.")
                        else:
                            LLM_PROVIDER = new_val
                            send_telegram(f"✅ Provider diganti ke <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>.\nBot akan coba <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b> dulu di siklus berikutnya.")
                            logger.info(f"LLM provider changed to {LLM_PROVIDER}")
                elif text.startswith("/paper"):
                    parts = text.split()
                    if len(parts) == 1:
                        send_telegram(f"📄 <b>Trade Mode</b>\nCurrent: <b>{'PAPER (DRY RUN)' if DRY_RUN else 'LIVE'}</b>\nUse /paper dry untuk paper trade, /paper live untuk real trade")
                    else:
                        requested = parts[1].strip().lower()
                        if requested in ("dry", "paper", "simulasi", "sim"):
                            new_val = True
                            label = "PAPER (DRY RUN)"
                        elif requested in ("live", "real", "nyata"):
                            new_val = False
                            label = "LIVE"
                        else:
                            send_telegram("⚠️ Pilih: /paper dry atau /paper live")
                            continue
                        if new_val == DRY_RUN:
                            send_telegram(f"✅ Mode sudah <b>{label}</b>.")
                        else:
                            DRY_RUN = new_val
                            send_telegram(f"✅ Mode diganti ke <b>{label}</b>.\nMulai siklus berikutnya akan pakai mode <b>{label}</b>.")
                            logger.info(f"Trade mode changed to {'DRY RUN' if DRY_RUN else 'LIVE'}")
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
                            hold = normalize_hold_side(hold)
                            price = parse_float(pos.get("markPrice", pos.get("openPriceAvg", 0)), 0.0)
                            pnl, fee, size, current, entry = estimate_position_net_pnl(pos, price)
                            res = {"code": "00000"} if DRY_RUN else close_position_api(sym, hold)
                            ok, close_reason = close_position_succeeded(res, sym, hold)
                            if ok:
                                save_trade_close_by_id(pos["id"], price, pnl) if DRY_RUN else save_trade_close(sym, price, pnl, hold)
                                clear_trailing_stop(sym, hold)
                                emoji = "✅" if pnl > 0 else "❌"
                                prefix = "DRY RUN " if DRY_RUN else ""
                                send_telegram(f"{emoji} <b>{prefix}CLOSED</b> {hold.upper()} {sym}\nNet PnL: <b>{pnl:.4f} USDT</b>\nEst. fees: <b>{fee:.4f} USDT</b>")
                            else:
                                send_telegram(f"⚠️ Failed to close {hold.upper()} {sym}: {close_reason}")
                                logger.error(f"Manual close failed for {hold} {sym}: {close_reason} | response={json.dumps(res, ensure_ascii=False)}")
                elif text == "/stop":
                    send_telegram("🛑 Bot stopped.")
                    bot_running = False
                elif text == "/help":
                    send_telegram_buttons(
                        f"📋 <b>Menu Bantuan</b>\n\n"
                        f"📊 Status — lihat posisi + PnL\n"
                        f"💰 Balance — saldo + daily PnL\n"
                        f"📈 History — statistik trading\n"
                        f"⚡ Trade — scan sinyal sekarang\n"
                        f"⚡ Force — paksa buka posisi\n"
                        f"🧠 Model — ganti model LLM\n"
                        f"🔌 Provider — ganti LLM provider\n"
                        f"📄 Paper/Live — ganti mode trading\n"
                        f"⚙️ Mode — scalping / normal\n"
                        f"🤖 Auto TP/SL — LLM atur TP/SL atau manual\n"
                        f"🛑 Stop — matikan bot\n\n"
                        f"<b>Settings:</b>\n"
                        f"Trade: <b>{'PAPER' if DRY_RUN else 'LIVE'}</b>\n"
                        f"Provider: <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>\n"
                        f"Mode: {TRADE_MODE.upper()}\n"
                        f"Auto TP/SL: {'✅' if LLM_MANAGE_ENTRY else '❌'}\n"
                        f"TP: {TAKE_PROFIT_ROI_PCT:.0f}% | SL: {STOP_LOSS_ROI_PCT:.0f}%\n"
                        f"Scan: every {SLEEP_MINUTES} min",
                        [[("🔙 Menu", "menu:main")]])
            time.sleep(1)
        except Exception as e:
            logger.error(f"handle_commands error: {e}")
            time.sleep(1)

def main():
    global bot_running
    logger.info("=== Bitget LLM Bot V2 (Learning Edition) ===")
    send_telegram_buttons(f"🤖 <b>Bitget LLM Bot</b>\nMode: <b>{'PAPER' if DRY_RUN else 'LIVE'} / {TRADE_MODE.upper()}</b>\nProvider: <b>{LLM_PROVIDER_LABELS[LLM_PROVIDER]}</b>\nModel: <code>{active_llm_model()}</code>\nScan: <b>every {SLEEP_MINUTES} min</b>\nAuto TP/SL: <b>{'✅' if LLM_MANAGE_ENTRY else '❌'}</b>\nTP: <b>{TAKE_PROFIT_ROI_PCT:.0f}%</b> | SL: <b>{STOP_LOSS_ROI_PCT:.0f}%</b>", main_menu())
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
                        entry = parse_float(p.get("openPriceAvg", 0), 0.0)
                        pnl, fee, size, current, entry = estimate_position_net_pnl(p, parse_float(ticker.get("lastPr"), entry))
                    else:
                        pnl, fee, size, current, entry = estimate_position_net_pnl(p, parse_float(p.get("markPrice", 0), 0.0))
                    logger.info(f"Position: {p.get('holdSide','').upper()} {p['symbol']} | Net PnL: {pnl:.4f} | Est. fees: {fee:.4f}")
                manage_positions()
            find_and_trade()
            if DRY_RUN and get_strategy_positions():
                logger.info(f"Dry-run positions active; sleeping {DRY_RUN_POLL_SECONDS} sec...")
                sleep_until_next_cycle(DRY_RUN_POLL_SECONDS)
            elif not force_trade:
                logger.info(f"Sleeping {SLEEP_MINUTES} min...")
                sleep_until_next_cycle(SLEEP_MINUTES * 60)
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
