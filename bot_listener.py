import os
import time
import requests
from dotenv import load_dotenv

from naukri_auto_apply import run_automation, send_telegram

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DRY_RUN = os.getenv("DRY_RUN", "False")
MATCH_THRESHOLD = os.getenv("MATCH_THRESHOLD", "85")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def get_updates(offset=None):
    try:
        url = f"{BASE_URL}/getUpdates?timeout=30"
        if offset:
            url += f"&offset={offset}"
        response = requests.get(url, timeout=35)
        return response.json()
    except Exception as e:
        print(f"Polling error: {e}")
        return {}


def handle_command(text: str):
    cmd = text.strip().lower()

    if cmd in ["/scan", "/run", "scan", "run"]:
        send_telegram("⏳ *Trigger received!* Scanning Gmail now...")
        print("\n[Telegram Trigger] Scanning Gmail for recruiter emails...")
        try:
            run_automation()
        except Exception as e:
            send_telegram(f"❌ Error during scan: {e}")

    elif cmd in ["/status", "status"]:
        status_msg = (
            f"🤖 *Career Bot Status: ONLINE (Gmail Mode)*\n\n"
            f"• *Threshold:* {MATCH_THRESHOLD}%\n"
            f"• *Dry Run:* {DRY_RUN}\n"
            f"• *Engine:* Gmail API + Gemini 3.8 Flash\n\n"
            f"Send `/scan` anytime to trigger an immediate check."
        )
        send_telegram(status_msg)

    elif cmd in ["/help", "help", "/start"]:
        help_msg = (
            f"📋 *Bot Commands:*\n\n"
            f"• `/scan` - Scan Gmail and auto-reply to recruiters\n"
            f"• `/status` - Check current settings\n"
            f"• `/help` - Show this menu"
        )
        send_telegram(help_msg)


def start_listener():
    print("=" * 55)
    print("🤖 Gmail Recruitment Bot Listener is active...")
    print("Supports: /scan, /status, /help")
    print("=" * 55)

    send_telegram("🟢 *Gmail Recruitment Bot Online!*\nSend `/scan` anytime to check your inbox.")

    offset = None
    while True:
        updates = get_updates(offset)
        if updates.get("ok"):
            for result in updates.get("result", []):
                offset = result["update_id"] + 1
                message = result.get("message", {})
                chat_id = str(message.get("chat", {}).get("id", ""))
                text = message.get("text", "")

                if chat_id == str(TELEGRAM_CHAT_ID) and text:
                    print(f"Received command: '{text}'")
                    handle_command(text)

        time.sleep(1)


if __name__ == "__main__":
    start_listener()