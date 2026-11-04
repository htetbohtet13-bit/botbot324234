import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from urllib.error import URLError
from urllib.request import Request, urlopen


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
            request = Request(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data=json.dumps({"chat_id": chat["id"], "text": "Hi! Your bot is connected."}).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=8):
                    pass
            except (URLError, TimeoutError) as error:
                if getattr(error, "code", None) != 403:
                    self.send_error(502, "Telegram could not deliver the reply")
                    return

        self.send_response(204)
        self.end_headers()
