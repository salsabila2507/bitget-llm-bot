# Bitget LLM Trading Bot V2

AI-powered futures trading bot with learning system for small capital ($1-10).

## Features
- Max 2 positions | SL -10% | TP $0.50
- Learning from trade history
- Auto blacklist bad pairs
- Multi-timeframe LLM analysis (Groq)

## Quick Setup

### 1. Get API Keys
- **Bitget:** https://www.bitget.com (Classic Account, Futures permission)
- **Groq:** https://console.groq.com (free)
- **Telegram:** @BotFather

### 2. Install
```bash
git clone https://github.com/salsabila2507/bitget-llm-bot.git
cd bitget-llm-bot
pip3 install requests --break-system-packages
```

### 3. Configure
Edit `bitget_llm_trader_clean.py`, replace:
```python
API_KEY = "your_bitget_api_key"
SECRET_KEY = "your_bitget_secret"
PASSPHRASE = "your_passphrase"
GROQ_API_KEY = "gsk_your_groq_key"
TELEGRAM_TOKEN = "your_bot_token"
TELEGRAM_CHAT_ID = "your_chat_id"
```
Save as `bitget_llm_trader.py`

### 4. Run
```bash
python3 bitget_llm_trader.py
```

## Production (Systemd)
```bash
sudo tee /etc/systemd/system/bitget-trader.service << 'EOF'
[Unit]
Description=Bitget LLM Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/bitget-llm-bot
ExecStart=/usr/bin/python3 /root/bitget-llm-bot/bitget_llm_trader.py
Restart=always
StandardOutput=append:/root/bitget-llm-bot/bot.log

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable bitget-trader
sudo systemctl start bitget-trader
```

## Telegram Commands
- `/status` - positions + PnL
- `/balance` - balance
- `/history` - stats
- `/trade` - force trade
- `/close` - close all

## Troubleshooting

**Spam messages:**
```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates?offset=-1" > /dev/null
sudo systemctl restart bitget-trader
```

**Multiple instances:**
```bash
pkill -9 -f bitget_llm_trader
sudo systemctl start bitget-trader
```

## Disclaimer
⚠️ High risk. Test with $1 first. Not financial advice.

MIT License
