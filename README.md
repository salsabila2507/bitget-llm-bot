# King Bitget Bot

LLM-assisted Bitget USDT futures bot with dry-run learning mode, Telegram controls, and selectable normal/scalping trade profiles.

## Current Mode

The bot defaults to dry-run first, but dry-run/live and trade profile can now be controlled from environment variables, `.env`, or `.runtime.env`:

- `DRY_RUN=true` or `BITGET_DRY_RUN=true`
- `TRADE_MODE=scalping` or `TRADE_MODE=normal`
- `MAX_POSITIONS=2`
- Paper balance: `5.0 USDT`
- Default trade mode: `scalping`
- No real Bitget orders are placed while dry-run is enabled
- Simulated trades are saved to the local SQLite trade history

To run live/normal trading, set `DRY_RUN=false` and `TRADE_MODE=normal` in the runtime environment. Live mode uses the same learning filters, position management, TP/SL, trailing stop, time stop, and trade-history logging path as dry-run.

## Environment

Secrets must stay out of Git. Commit `.env.example` only, then keep real values in local `.env` or `.runtime.env`; both are ignored by `.gitignore`.

```bash
cp .env.example .env
```

Required secret values:

```text
BITGET_API_KEY=
BITGET_SECRET_KEY=
BITGET_PASSPHRASE=
NVIDIA_API_KEY=
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
```

Runtime toggles:

```text
DRY_RUN=true
TRADE_MODE=scalping
MAX_POSITIONS=2
MAX_ORDERS_PER_CYCLE=1
```

## Strategy Rules

- Analyze the top 50 tickers by volume
- Send the top 10 signals to Telegram
- Maximum 2 open positions
- Open at most 1 new auto position per scan cycle
- Trade only when confidence meets the active mode threshold
- Track net PnL after estimated taker fees
- Learn from recent trade history, pair performance, LONG/SHORT results, and pair+direction performance
- Avoid pair/direction combinations that show weak recent net PnL after fees

## Trade Modes

### Scalping

Default active mode.

- Scan interval: 5 minutes
- TP: 10% ROI
- SL: 6% ROI
- Min confidence: 80%
- Intended for small dry-run capital and faster simulated exits

### Normal

Original slower trading profile.

- Scan interval: 60 minutes
- TP: 70% ROI
- SL: 40% ROI
- Min confidence: 70%

Switch mode from Telegram:

```text
/mode scalping
/mode normal
```

## LLM Provider

The bot uses the NVIDIA OpenAI-compatible API.

Kimi 2.6 was checked but timed out in the current setup, so the active fallback model is:

```text
meta/llama-3.3-70b-instruct
```

## Telegram Commands

```text
/status              positions + PnL
/balance             paper balance, real balance, daily PnL
/history             trade stats
/trade               force a scan now
/mode                show current mode
/mode scalping       switch to scalping mode
/mode normal         switch to normal mode
/close               close all positions
/close SYMBOL        close one position
/stop                stop the bot
/help                show commands
```

Only configured Telegram chat IDs are allowed to control the bot.

## Run

From the project directory:

```bash
cd /root/bitget-llm-bot
python3 -m py_compile bitget_llm_trader.py
setsid -f env BITGET_BOT_DAEMON=1 python3 -u bitget_llm_trader.py > bot.log 2>&1 < /dev/null
```

Check status:

```bash
pgrep -af bitget_llm_trader.py
tail -n 50 bot.log
```

Stop:

```bash
pkill -f '[b]itget_llm_trader.py'
```

## Runtime Notes

- The bot needs network access to `api.bitget.com`, Telegram, and the NVIDIA API.
- If Bitget DNS/network fails, the bot may stay alive but cannot fetch fresh tickers or update dry-run PnL correctly.
- If there are already 2 open dry-run positions, the bot will continue scanning and sending signals but will not open another simulated trade until a position closes.
- Dry-run mode is for learning and validation only. It does not guarantee real trading profit.

## Disclaimer

This is experimental trading automation. Futures trading is high risk. Dry-run results are not proof of live-market profitability.
