from telethon import TelegramClient
from dotenv import load_dotenv
import os

# Načtení proměnných z .env souboru
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("❌ Chyba: API_ID nebo API_HASH nebyly načteny.")
    exit()

try:
    API_ID = int(API_ID)  # ujisti se, že je to číslo
except ValueError:
    print("❌ API_ID musí být celé číslo.")
    exit()

# Inicializace klienta
client = TelegramClient('test_session', API_ID, API_HASH)

async def main():
    print("🔐 Přihlašuji se k Telegramu...")
    await client.start()
    me = await client.get_me()
    print("✅ Přihlášení úspěšné!")
    print(f"👤 Uživatelské jméno: {me.username}")
    print(f"🆔 ID: {me.id}")

with client:
    client.loop.run_until_complete(main())
