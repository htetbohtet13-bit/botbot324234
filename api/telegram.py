import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from secrets import token_hex
from time import sleep
from urllib.error import URLError
from urllib.request import Request, urlopen


WELCOME_TEXT = """ကြိုဆိုပါတယ်ရှင့်🙏🏻

📌ဘောနပ်စ်——
🎁အကောင့်ဖွင့်ပြီး 10,000ကျပ်ထိဖရီးယူ

⭐️ငွေသွင်း/ငွေထုတ် ချက်ချင်းရ
⭐️RTP 97% | နိုင်ခြေအမြင့်ဆုံး
✅တရားဝင် လိုင်စင်ရပြီး

App ဒေါင်းရန်👇👇👇"""
GAME_LINK_TEXT = "🔗 ဂိမ်းတိုက်ရိုက်လင့် \nhttps://j777ml.com"
APK_PATH = Path(__file__).resolve().parent.parent / "assets" / "J777-v1.0.3.apk"


def send_telegram(bot_token, method, body, content_type="application/json"):
    request = Request(
        f"https://api.telegram.org/bot{bot_token}/{method}",
        data=body,
        headers={"Content-Type": content_type},
    )
    with urlopen(request, timeout=8):
        pass


def send_start_messages(bot_token, chat_id):
    boundary = token_hex(16)
    document = b"".join(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{APK_PATH.name}"\r\n'.encode(),
            b"Content-Type: application/vnd.android.package-archive\r\n\r\n",
            APK_PATH.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        )
    )

    welcome = json.dumps({"chat_id": chat_id, "text": WELCOME_TEXT}).encode()
    send_telegram(bot_token, "sendMessage", welcome)
    sleep(1)
    send_telegram(bot_token, "sendDocument", document, f"multipart/form-data; boundary={boundary}")
    sleep(1)
    link = json.dumps(
        {"chat_id": chat_id, "text": GAME_LINK_TEXT, "link_preview_options": {"is_disabled": True}}
    ).encode()
    send_telegram(bot_token, "sendMessage", link)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"Telegram webhook is reachable.\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET")
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not secret or not bot_token:
            self.send_error(503, "Telegram webhook settings are missing")
            return

        supplied_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(secret.encode(), supplied_secret.encode()):
            self.send_error(403)
            return

        try:
            update = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        except ValueError:
            self.send_error(400, "Invalid Telegram update")
            return

        message = update.get("message", {})
        chat = message.get("chat", {})
        words = message.get("text", "").split(maxsplit=1)
        if chat.get("type") == "private" and words and words[0] == "/start":
            try:
                send_start_messages(bot_token, chat["id"])
            except (URLError, TimeoutError) as error:
                if getattr(error, "code", None) != 403:
                    self.send_error(502, "Telegram could not deliver the reply")
                    return

        self.send_response(204)
        self.end_headers()
