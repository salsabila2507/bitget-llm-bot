# Bitget LLM Trading Bot

An autonomous Bitget Futures trading bot powered by LLM (BlueMind API). The bot analyzes market data, selects the best trading pair, opens positions, monitors them, and closes at take profit — all automatically.

---

## Requirements

- Python 3.10+
- VPS running Ubuntu (recommended)
- Bitget account (Classic mode) with Futures wallet funded
- BlueMind API key (https://bluesminds.com)
- Telegram bot token + chat ID

---

## Installation

### 1. Clone the repo
```bash
git clone https://github.com/salsabila2507/bitget-llm-bot.git
cd bitget-llm-bot
```

### 2. Install dependencies
```bash
pip install requests
```

### 3. Configure the bot
```bash
cp bitget_llm_trader.py.example bitget_llm_trader.py
nano bitget_llm_trader.py
```

Fill in your credentials:
```python
API_KEY    = "your_bitget_api_key"
SECRET_KEY = "your_bitget_secret_key"
PASSPHRASE = "your_bitget_passphrase"

BLUEMIND_API_KEY = "your_bluemind_api_key"

TELEGRAM_TOKEN   = "your_telegram_bot_token"
TELEGRAM_CHAT_ID = "your_telegram_chat_id"
```

### 4. Run manually (for testing)
```bash
python3 bitget_llm_trader.py
```

### 5. Run as a systemd service (recommended for VPS)
```bash
sudo cp bitget-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bitget-bot
sudo systemctl start bitget-bot
```

Check status:
```bash
systemctl status bitget-bot
tail -f /root/bitget_bot.log
```

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | Show active positions and PnL |
| `/balance` | Show available balance |
| `/history` | Show trade history and win rate |
| `/trade` | Force bot to search and open a position now |
| `/close` | Close all active positions |
| `/close SYMBOL` | Close a specific position (e.g. `/close ONTUSDT`) |
| `/stop` | Stop the bot |
| `/help` | Show all commands |

---

## Configuration

Edit these values in `bitget_llm_trader.py`:
```python
MIN_NOTIONAL      = 5.5    # Minimum trade size in USD
MAX_PRICE         = 1.0    # Only trade pairs priced below $1
MIN_LEVERAGE      = 10     # Minimum leverage
MAX_LEVERAGE      = 50     # Maximum leverage
SLEEP_MINUTES     = 15     # How often the bot checks (minutes)
TP_USD            = 1.0    # Auto close when profit reaches $1
MIN_LOSS_TO_CLOSE = -0.10  # Ask LLM to close only if loss exceeds this
```

---

## Choosing an LLM Model

Edit this line in `bitget_llm_trader.py`:
```python
LLM_MODEL = "mistralai/mistral-small-3.1-24b-instruct-2503"
```

| Model | Speed | Quality | Notes |
|-------|-------|---------|-------|
| `meta/llama-3.1-8b-instruct` | ⚡ Fast | ⭐⭐ | Too conservative, always HOLDs |
| `mistralai/mistral-small-3.1-24b-instruct-2503` | ✅ Good | ⭐⭐⭐⭐ | **Recommended default** |
| `deepseek-ai/deepseek-r1-distill-qwen-14b` | ✅ Good | ⭐⭐⭐⭐ | Good alternative |
| `qwen/qwq-32b` | ✅ Good | ⭐⭐⭐⭐ | Good alternative |
| `meta/llama-3.3-70b-instruct` | 🐢 Slow | ⭐⭐⭐⭐⭐ | Frequently times out on BlueMind |

To see all available models:
```python
import requests
r = requests.get(
    'https://api.bluesminds.com/v1/models',
    headers={'Authorization': 'Bearer YOUR_BLUEMIND_API_KEY'}
)
for m in r.json().get('data', []):
    print(m.get('id'))
```

---

## How It Works

1. Bot fetches top 10 cheap pairs (price < $1) by volume
2. Collects 15m candle data, calculates RSI, MA9, MA21
3. Sends data + trade history to LLM for decision
4. LLM picks the best pair and direction (LONG/SHORT)
5. Bot opens position with isolated margin
6. Every 15 minutes, bot checks PnL:
   - If PnL >= $1 → auto close (take profit)
   - If loss < -$0.10 → ask LLM whether to close or hold
   - Otherwise → hold
7. After position closes, bot searches for new entry

---

## Bitget API Setup

1. Go to Bitget → Profile → API Management
2. Create new API key with permissions:
   - Read
   - Futures Order
   - Futures Position
3. Whitelist your VPS IP address
4. Save API Key, Secret Key, and Passphrase

---

## Notes

- Minimum recommended balance: **$5 USDT** in Futures wallet
- Bot only opens **1 position at a time**
- All positions use **isolated margin**
- Trade history is saved to `/root/trade_history.db`
- Logs are saved to `/root/bitget_bot.log`
