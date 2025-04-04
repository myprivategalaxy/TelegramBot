import re
import time
import random
import logging
import json
import os
import asyncio
import aiohttp
from aiohttp import web
from telethon import TelegramClient, events
from dotenv import load_dotenv

# Načtení proměnných z .env souboru (předpokládá se, že .env je ve stejné složce)
load_dotenv()

# Načtení API klíčů z .env
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# Telegram kanály – zadejte správné ID
SOURCE_CHANNEL = -1001525644349       # Zdrojový kanál (automatické signály)
DESTINATION_CHANNEL = -4501979545      # Kanál, kam se posílají zpracované signály

# Webhook adresy
WEBHOOK_URL = "http://168.119.174.213:5001/webhook"
TRADE_BOT_WEBHOOK_URL = "http://168.119.174.213:5002/webhook"

client = TelegramClient('bot_session', API_ID, API_HASH)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

IGNORE_RATE = 0  # Pro ladění
MIN_DELAY = 60
MAX_DELAY = 120

ALLOWED_KEYWORDS = [
    "VIP Trade ID", "Pair:", "Direction:", "Position Size:",
    "Leverage", "Trade Type:", "ENTRY", "Target", "STOP LOSS"
]
SIGNALS_FILE = "signals.json"

def should_forward_message(message: str) -> bool:
    if re.search(r'\bprofit\b', message, re.IGNORECASE):
        return False
    return True

def save_signal(signal):
    try:
        if not os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                json.dump({"signals": []}, f)
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if any(existing.get("signal_id") == signal.get("signal_id") for existing in data.get("signals", [])):
            return
        data["signals"].append(signal)
        with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logging.error(f"Error saving signal: {e}")

def typewriter_effect(text, total_duration=3):
    if len(text) == 0:
        return
    delay = total_duration / len(text)
    for char in text:
        print(char, end='', flush=True)
        time.sleep(delay)
    print()

def greet():
    greeting = (
        "Wake up, Neo... The Matrix has you... Follow the white rabbit. "
        "Knock, knock, Neo. Bot developed by Jiri Gazo."
    )
    print("\033[32m", end='')
    typewriter_effect(greeting, total_duration=3)
    print("\033[0m", end='')

greet()
logging.info("This bot was developed by Jiri Gazo.")

def parse_with_chatgpt(message):
    prompt = f"""
Parse the following trading signal and return a JSON object with the keys:
- "signal_id": string,
- "symbol": string (e.g., "BTCUSDT"),
- "direction": string ("BUY" or "SELL"),
- "entry": number or list of numbers,
- "stop_loss": number,
- "target": number or list of numbers,
- "position_size": string,
- "leverage": string,
- "trade_type": string.
If any value is missing, return null for that key.
Signal: {message}
Return only valid JSON, without any extra commentary.
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert trading signal parser. Return only JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=300
        )
        content = response.choices[0].message.content.strip()
        return json.loads(content)
    except Exception as e:
        print("❌ ChatGPT fallback parser error:", e)
        return None

def get_tick_size(symbol, exchange_info):
    for s in exchange_info.get("symbols", []):
        if s.get("symbol") == symbol:
            for f in s.get("filters", []):
                if f.get("filterType") == "PRICE_FILTER":
                    return float(f.get("tickSize"))
    return None

def round_price(price, tick_size):
    if tick_size is None or tick_size == 0:
        return price
    precision = abs(int(round(math.log10(tick_size))))
    return round(price, precision)

def round_quantity(qty, step_size):
    if step_size is None or step_size == 0:
        return qty
    precision = abs(int(round(math.log10(step_size))))
    return round(qty, precision)

def calculate_atr(symbol, interval='1h', period=14, limit=100):
    try:
        # Předpokládáme, že obchodní bot již má svůj vlastní kód pro ATR výpočet
        klines = []  # Tady bude volání Binance API v obchodním botu
        # Pro demo účely vracíme fixní hodnotu
        return 100
    except Exception as e:
        print(f"❌ ATR calculation error for {symbol}: {e}")
        return 100

def get_current_price(symbol):
    try:
        # Tady opět předpokládáme volání Binance API; pro demo účely vracíme fixní cenu
        return 65000.0
    except Exception as e:
        print(f"❌ Error fetching current price for {symbol}: {e}")
        return None

def reformat_signal(raw_text):
    lines = raw_text.splitlines()
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(keyword in line for keyword in ALLOWED_KEYWORDS):
            line = re.sub(r'^[^\w]+', '', line)
            if "Pair:" in line:
                line = re.sub(r'\s*\(.*?\)', '', line)
            if "Direction:" in line:
                line = "Direction: " + re.sub(r'[^A-Za-z\s]', '', line.split(":", 1)[1]).strip()
            line = re.sub(r'\s*-\s*', '-', line)
            clean_lines.append(line)
    return "\n".join(clean_lines)

def process_signal_text(message_text):
    if isinstance(message_text, dict):
        return {"data": message_text, "formatted": json.dumps(message_text, indent=4)}
    if not isinstance(message_text, str):
        message_text = str(message_text)
    message_text = reformat_signal(message_text)
    required_keywords = ["VIP Trade ID", "Pair:", "Direction:", "ENTRY", "Target", "STOP LOSS"]
    if not any(keyword in message_text for keyword in required_keywords):
        logging.info("Signál neobsahuje požadovaná klíčová slova. Použiji fallback ChatGPT parser.")
        fallback_result = parse_with_chatgpt(message_text)
        if fallback_result:
            return {"data": fallback_result, "formatted": json.dumps(fallback_result, indent=4)}
        else:
            return None
    signal_id = ""
    pair = ""
    direction = ""
    entry_price = 0.0
    stop_loss = 0.0
    targets = []
    position_size = ""
    leverage = ""
    trade_type = ""
    lines = message_text.splitlines()
    for line in lines:
        if line.startswith("VIP Trade ID:"):
            parts = line.split("#")
            if len(parts) > 1:
                signal_id = parts[1].strip()
            else:
                signal_id = line.split(":", 1)[1].strip()
        elif line.startswith("Pair:"):
            raw_pair = line.split(":", 1)[1].strip()
            pair = raw_pair.upper()
        elif line.startswith("Direction:"):
            direction = line.split(":", 1)[1].strip()
            if "LONG" in direction.upper():
                direction = "BUY"
            elif "SHORT" in direction.upper():
                direction = "SELL"
        elif line.startswith("Position Size:"):
            position_size = line.split(":", 1)[1].strip()
        elif line.startswith("Leverage"):
            leverage = line.split(":", 1)[1].strip() if ":" in line else ""
        elif line.startswith("Trade Type:"):
            trade_type = line.split(":", 1)[1].strip()
        elif line.startswith("ENTRY"):
            entry_str = line.split(":", 1)[1].strip()
            try:
                entry_price = float(entry_str.split("-")[0].strip()) if "-" in entry_str else float(entry_str)
            except ValueError:
                entry_price = 0.0
        elif "Target" in line and "-" in line:
            try:
                target_value = float(line.split("-")[1].strip())
                targets.append(target_value)
            except ValueError:
                continue
        elif "STOP LOSS" in line:
            try:
                stop_loss = float(line.split(":", 1)[1].strip())
            except ValueError:
                stop_loss = 0.0
    if not targets or stop_loss == 0.0:
        logging.error("Chybný formát signálu: chybí STOP LOSS nebo target.")
        fallback_result = parse_with_chatgpt(message_text)
        if fallback_result:
            return {"data": fallback_result, "formatted": json.dumps(fallback_result, indent=4)}
        else:
            return None
    data = {
        "signal_id": signal_id,
        "symbol": pair,
        "direction": direction,
        "entry": entry_price,
        "stop_loss": stop_loss,
        "target": targets,
        "position_size": position_size,
        "leverage": leverage,
        "trade_type": trade_type
    }
    formatted_signal = json.dumps(data, indent=4)
    return {"data": data, "formatted": formatted_signal}

@client.on(events.NewMessage(chats=(SOURCE_CHANNEL, DESTINATION_CHANNEL)))
async def forward_signal(event):
    message_text = event.message.text.strip() if event.message.text else ""
    if not message_text:
        return
    if not any(keyword in message_text for keyword in ALLOWED_KEYWORDS):
        return
    if not should_forward_message(message_text):
        return
    processed = process_signal_text(message_text)
    if not processed:
        return
    save_signal(processed["data"])
    if event.chat_id == SOURCE_CHANNEL:
        delay = random.uniform(MIN_DELAY, MAX_DELAY)
        remaining_time = delay
        while remaining_time > 0:
            await asyncio.sleep(min(remaining_time, 10))
            remaining_time -= 10
        try:
            await client.send_message(DESTINATION_CHANNEL, processed["formatted"])
            logging.info("✅ Zpráva byla odeslána do destination kanálu.")
        except Exception as e:
            logging.error(f"Error sending message to the destination channel: {e}")
    else:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(TRADE_BOT_WEBHOOK_URL, json=processed["data"]) as resp:
                    if resp.status == 200:
                        logging.info("✅ Trading bot webhook triggered from manual signal in destination channel.")
                    else:
                        logging.error(f"❌ Trading bot webhook error, status: {resp.status}")
        except Exception as e:
            logging.error(f"Error triggering trading bot webhook: {e}")

def format_open_trade_message(data):
    matrix_intro = "\n".join([
        "[ 01 ] INITIALIZING MATRIX...",
        "[ 02 ] DATA STREAM SYNCED",
        "[ 03 ] NEURAL TRADE INTERFACE ACTIVE",
        "🟢 Wake up, Neo...",
        "📡 The Matrix has you...",
        ""
    ])
    body = "\n".join([
        f"🚀 OPEN TRADE – {data.get('symbol', '-')} ({data.get('direction', '-')})",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 Entry:       {float(data.get('entry', 0)):.5f} USDT",
        f"📉 Stop Loss:   {float(data.get('stop_loss', 0)):.5f} USDT",
        f"🎯 Target:      {float(data.get('target', [0])[0]):.5f} USDT",
        f"🔸 Signal ID:   {data.get('signal_id', '-')}",
        "━━━━━━━━━━━━━━━━━━━━━━━"
    ])
    return "\n".join([matrix_intro, body])

def format_trade_update_message(data):
    return "\n".join([
        "🟢 SYSTEM UPDATE...",
        "🔄 TRADE STATUS CHANGED",
        f"📌 Symbol:      {data.get('symbol', '-')}",
        f"🟢 Message:     {data.get('message', '-')}",
        f"💰 Price:       {data.get('current_price', '-')}",
        f"📉 New SL:      {data.get('new_sl', '-')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ])

def format_close_trade_message(data):
    order = data.get("order", {})
    exit_price = "-"
    if "message" in data:
        parts = data.get("message").split()
        try:
            exit_price = f"{float(parts[-1]):.5f}"
        except Exception:
            exit_price = "-"
    return "\n".join([
        "🔴 Everything that has a beginning... has an end.",
        f"❌ TRADE CLOSED – {data.get('symbol', '-')}",
        "━━━━━━━━━━━━━━━━━━━━━━━",
        f"💸 Exit Price:     {exit_price} USDT",
        f"📝 Message:        {data.get('message', '-')}",
        f"🧾 Order ID:       {order.get('orderId', '-')}",
        "💀 Everything that has a beginning has an end, Neo."
    ])

async def handle_trade_notification(request):
    try:
        data = await request.json()
        event_type = data.get("event")
        if event_type == "open_trade":
            msg = format_open_trade_message(data)
        elif event_type == "trade_update":
            msg = format_trade_update_message(data)
        elif event_type == "close_trade":
            msg = format_close_trade_message(data)
        else:
            msg = f"ℹ️ Unknown notification:\n{json.dumps(data, indent=2)}"
        await client.send_message(DESTINATION_CHANNEL, msg)
        logging.info("✅ Notifikace odeslána do Telegram kanálu.")
        return web.Response(text="Notification processed", status=200)
    except Exception as e:
        logging.error(f"Error processing notification: {e}")
        return web.Response(text="Error", status=500)

app_webhook = web.Application()
app_webhook.router.add_post('/webhook', handle_trade_notification)

async def run_webhook_server():
    runner = web.AppRunner(app_webhook)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5001)
    await site.start()
    logging.info("🚀 Webhook server běží na http://0.0.0.0:5001/webhook")

async def main():
    webhook_server = asyncio.create_task(run_webhook_server())
    await client.start()
    await client.run_until_disconnected()
    webhook_server.cancel()

if __name__ == "__main__":
    asyncio.run(main())
