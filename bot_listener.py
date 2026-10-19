import os
import time
import requests
from dotenv import load_dotenv

from naukri_auto_apply import run_automation as run_naukri_scan, send_telegram
from linkedin_auto_apply import run_linkedin_automation

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

    if cmd in ["/naukri", "naukri"]:
        send_telegram("⏳ Starting *Naukri* Gmail scan...")
        try:
            run_naukri_scan()
        except Exception as e:
            send_telegram(f"❌ Error during Naukri scan: {e}")

    elif cmd in ["/linkedin", "linkedin"]:
        send_telegram("⏳ Starting *LinkedIn* Easy Apply scan...")
        try:
            # Runs headless in background
            run_linkedin_automation(headless=True)
        except Exception as e:
            send_telegram(f"❌ Error during LinkedIn scan: {e}")

    elif cmd in ["/scan", "/run", "scan", "run", "/all"]:
        send_telegram("⏳ Running full scan (*Naukri + LinkedIn*)...")
        try:
            print("[Trigger] Running Naukri...")
            run_naukri_scan()
            print("[Trigger] Running LinkedIn...")
            run_linkedin_automation(headless=True)
        except Exception as e:
            send_telegram(f"❌ Error during full scan: {e}")

    elif cmd in ["/status", "status"]:
        status_msg = (
            f"🤖 *Career Bot Status: ONLINE*\n\n"
            f"• *Threshold:* {MATCH_THRESHOLD}%\n"
            f"• *Dry Run:* {DRY_RUN}\n\n"
            f"Available Triggers:\n"
            f"• `/naukri` - Scan Naukri emails\n"
            f"• `/linkedin` - Scan LinkedIn Easy Apply\n"
            f"• `/scan` - Scan both platforms"
        )
        send_telegram(status_msg)

    elif cmd in ["/help", "help", "/start"]:
        help_msg = (
            f"📋 *Available Commands:*\n\n"
            f"• `/scan` - Run full scan (Naukri + LinkedIn)\n"
            f"• `/naukri` - Check Naukri recruiter reach-outs\n"
            f"• `/linkedin` - Check LinkedIn Easy Apply jobs\n"
            f"• `/status` - Show active configuration\n"
            f"• `/help` - Show this menu"
        )
        send_telegram(help_msg)


def start_listener():
    print("=" * 55)
    print("🤖 Unified Career Bot Listener is active...")
    print("Supports: /naukri, /linkedin, /scan, /status")
    print("=" * 55)

    send_telegram("🟢 *Unified Bot Online!*\nSupports: `/naukri`, `/linkedin`, and `/scan`")

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