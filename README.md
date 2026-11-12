# LZT Auto-Buyer Bot

Private Telegram bot that:

1. Logs worker accounts via Telethon (phone → OTP → 2FA).
2. Polls capacity bots every 5 min (`/cap` / `/capacity` / `/start`).
3. Parses country codes + prices from heterogeneous formats.
4. Marks countries FULL when they disappear from capacity replies.
5. Continuously searches lzt.market Telegram category with filters:
   - Session ≤ 1 day
   - Password: No
   - Login mail: Yes
   - Spam block: No
6. Buys at ≤ 50 % of the receiver sell price (1× profit).
7. Posts bought sessions + `.session` file to IDS CHANNEL.
8. Owner-only UI with inline buttons.

## New Features (v2)

- **Analytics dashboard**: today / week / all-time spend, success rate, avg buy vs sell, best/worst countries.
- **Notifications**: budget ≥80 %, country FULL / reopened, failed buys (critical), daily summary.
- **Country pause**: pause buying for a specific country for N minutes.
- **Session export**: export only sessions bought in the last 1 / 6 / 24 hours (or all) as zip.
- **Worker status view**.
- **Price history** recorded on every capacity poll.
- **Emergency STOP ALL** (persists across restarts).
- Stronger error paths and owner alerts on any money-related failure.

## Setup

```bash
cd lzt_autobuyer
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — BOT_TOKEN, OWNER_ID, IDS_CHANNEL_ID, API_ID, API_HASH, LZT_TOKEN
```

### First worker session

1. Start the bot: `python -m bot.main`
2. Open the bot in Telegram as the owner.
3. Press **Add Worker** → send phone → paste OTP → (if asked) 2FA password.
4. Press **Refresh Rates** to pull capacity from the six bots.
5. Toggle Auto-Buy ON.

### Capacity bots polled

- @CM_Receiver6_Bot
- @Crazy_TimeAcc2_robot
- @tg_get2_bot
- @sttar1_bot
- @TBUNLIMITED2_BOT
- @TGLionAPI_bot

### LZT SDK

Uses the official `lolzteam` package (`MarketClient.categories.telegram.get` + `purchasing.purchasing_fast_buy`).

### Safety

- All LZT buy attempts are wrapped in try/except.
- Failed buys alert the owner immediately.
- Emergency stop sets `auto_buy=0` in DB and pauses the loop.
- Daily budget hard-stop is checked before every purchase.
