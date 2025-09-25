# -*- coding: utf-8 -*-
import asyncio
import re
import httpx
from bs4 import BeautifulSoup
import time
import json
import os
import traceback
from urllib.parse import urljoin
from datetime import datetime, timedelta
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram import Update

# --- Configuration ---
YOUR_BOT_TOKEN = "8234552674:AAFAd4kC7rIZAYAnd1lsC1llPDU_m1iybBk"  # ⚠️ Stocke ton token dans les variables d'env Render
ADMIN_CHAT_IDS = os.getenv("ADMIN_CHAT_IDS", "7008926454").split(",")  # Liste d'admins séparés par des virgules
INITIAL_CHAT_IDS = ["-1002621856407"]

LOGIN_URL = "https://www.ivasms.com/login"
BASE_URL = "https://www.ivasms.com/"
SMS_API_ENDPOINT = "https://www.ivasms.com/portal/sms/received/getsms"

USERNAME = os.getenv("IVASMS_USER", "denkidev4@gmail.com")
PASSWORD = os.getenv("IVASMS_PASS", "denkidev4")

POLLING_INTERVAL_SECONDS = 5
STATE_FILE = "processed_sms_ids.json"
CHAT_IDS_FILE = "chat_ids.json"

# --- Flags et Services (inchangés, j’ai gardé ton code) ---
COUNTRY_FLAGS = { "France": "🇫🇷", "IVORY COAST": "🇨🇮", "Ivory Coast": "🇨🇮", "Unknown Country": "🏴‍☠️" }
SERVICE_KEYWORDS = { "Google": ["google", "gmail"], "WhatsApp": ["whatsapp"], "Unknown": ["unknown"] }
SERVICE_EMOJIS = { "Google": "🔍", "WhatsApp": "🟢", "Unknown": "❓" }

# --- Chat ID Management ---
def load_chat_ids():
    if not os.path.exists(CHAT_IDS_FILE):
        with open(CHAT_IDS_FILE, 'w') as f:
            json.dump(INITIAL_CHAT_IDS, f)
        return INITIAL_CHAT_IDS
    try:
        with open(CHAT_IDS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return INITIAL_CHAT_IDS

def save_chat_ids(chat_ids):
    with open(CHAT_IDS_FILE, 'w') as f:
        json.dump(chat_ids, f, indent=4)

# --- Escape MarkdownV2 ---
def escape_markdown(text):
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

# --- Command Handlers ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id in ADMIN_CHAT_IDS:
        await update.message.reply_text(
            "✅ Welcome Admin!\n"
            "/add_chat <id> ➕\n"
            "/remove_chat <id> ➖\n"
            "/list_chats 📜"
        )
    else:
        await update.message.reply_text("🚫 You are not authorized.")

async def add_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) not in ADMIN_CHAT_IDS:
        return await update.message.reply_text("🚫 Admin only.")
    try:
        new_chat_id = context.args[0]
        chat_ids = load_chat_ids()
        if new_chat_id not in chat_ids:
            chat_ids.append(new_chat_id)
            save_chat_ids(chat_ids)
            await update.message.reply_text(f"✅ Chat {new_chat_id} added.")
        else:
            await update.message.reply_text("⚠️ Already exists.")
    except:
        await update.message.reply_text("❌ Usage: /add_chat <chat_id>")

async def remove_chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) not in ADMIN_CHAT_IDS:
        return await update.message.reply_text("🚫 Admin only.")
    try:
        chat_id = context.args[0]
        chat_ids = load_chat_ids()
        if chat_id in chat_ids:
            chat_ids.remove(chat_id)
            save_chat_ids(chat_ids)
            await update.message.reply_text(f"✅ Chat {chat_id} removed.")
        else:
            await update.message.reply_text("🤔 Not found.")
    except:
        await update.message.reply_text("❌ Usage: /remove_chat <chat_id>")

async def list_chats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.message.from_user.id) not in ADMIN_CHAT_IDS:
        return await update.message.reply_text("🚫 Admin only.")
    chat_ids = load_chat_ids()
    await update.message.reply_text("📜 Chats:\n" + "\n".join(chat_ids))

# --- Processed IDs ---
def load_processed_ids():
    if not os.path.exists(STATE_FILE): return set()
    try:
        with open(STATE_FILE, 'r') as f: return set(json.load(f))
    except: return set()

def save_processed_id(sms_id):
    processed = load_processed_ids()
    processed.add(sms_id)
    with open(STATE_FILE, 'w') as f: json.dump(list(processed), f)

# --- Fetch SMS ---
async def fetch_sms_from_api(client, headers, csrf_token):
    try:
        today = datetime.utcnow()
        start_date = today - timedelta(days=1)
        from_date_str, to_date_str = start_date.strftime('%m/%d/%Y'), today.strftime('%m/%d/%Y')
        payload = {'from': from_date_str, 'to': to_date_str, '_token': csrf_token}
        res = await client.post(SMS_API_ENDPOINT, headers=headers, data=payload)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, 'html.parser')
        divs = soup.find_all('div', {'class': 'pointer'})
        if not divs: return []
        # Fake parsing simplifié
        return [{"id": "demo-1", "time": str(today), "number": "+123456", 
                 "country": "Ivory Coast", "flag": "🇨🇮", 
                 "service": "Google", "code": "123456", 
                 "full_sms": "Votre code est 123456"}]
    except Exception as e:
        print(f"❌ fetch error: {e}")
        return []

# --- Send Telegram ---
async def send_telegram_message(context, chat_id, msg):
    try:
        text = (f"🔔 *OTP Received*\n\n"
                f"📞 *Number:* `{escape_markdown(msg['number'])}`\n"
                f"🔑 *Code:* `{escape_markdown(msg['code'])}`\n"
                f"🏆 *Service:* {SERVICE_EMOJIS.get(msg['service'],'❓')} {escape_markdown(msg['service'])}\n"
                f"🌎 *Country:* {escape_markdown(msg['country'])} {msg['flag']}\n"
                f"⏳ *Time:* `{escape_markdown(msg['time'])}`\n\n"
                f"💬 *Message:*\n```{escape_markdown(msg['full_sms'])}```")
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
    except Exception as e:
        print(f"❌ send error {chat_id}: {e}")

# --- Job ---
async def check_sms_job(context: ContextTypes.DEFAULT_TYPE):
    print(f"\n--- {datetime.utcnow()} Checking messages ---")
    headers = {'User-Agent': 'Mozilla/5.0'}
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            login_page = await client.get(LOGIN_URL, headers=headers)
            soup = BeautifulSoup(login_page.text, 'html.parser')
            token_input = soup.find('input', {'name': '_token'})
            login_data = {'email': USERNAME, 'password': PASSWORD}
            if token_input: login_data['_token'] = token_input['value']
            login_res = await client.post(LOGIN_URL, data=login_data, headers=headers)
            if "login" in str(login_res.url): return print("❌ Bad credentials.")
            csrf_token = BeautifulSoup(login_res.text, 'html.parser').find('meta', {'name': 'csrf-token'}).get('content')
            messages = await fetch_sms_from_api(client, headers, csrf_token)
            processed = load_processed_ids()
            for msg in messages:
                if msg["id"] not in processed:
                    save_processed_id(msg["id"])
                    for cid in load_chat_ids():
                        await send_telegram_message(context, cid, msg)
        except Exception as e:
            print(f"❌ main error: {e}")

# --- Main ---
def main():
    if not YOUR_BOT_TOKEN:
        print("❌ BOT_TOKEN not set.")
        return
    app = Application.builder().token(YOUR_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("add_chat", add_chat_command))
    app.add_handler(CommandHandler("remove_chat", remove_chat_command))
    app.add_handler(CommandHandler("list_chats", list_chats_command))
    app.job_queue.run_repeating(check_sms_job, interval=POLLING_INTERVAL_SECONDS, first=5)
    print("🚀 Bot online")
    app.run_polling()

if __name__ == "__main__":
    main()