# Bitget LLM Trading Bot

Automated Bitget Futures trading bot powered by LLM (BlueMind).

## Features
- Auto-select top cheap pairs (price < $1)
- LLM analyzes market data and decides LONG/SHORT
- LLM monitors open positions and decides HOLD/CLOSE
- Telegram bot integration (/status, /balance, /close, /stop)
- Auto-restart via systemd

## Setup
1. Copy `bitget_llm_trader.py.example` to `bitget_llm_trader.py`
2. Fill in your API keys
3. Run: `python3 bitget_llm_trader.py`

## Systemd service

