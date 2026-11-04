import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from secrets import token_hex
from time import sleep
from urllib.error import URLError
from urllib.request import Request, urlopen

import psycopg


WELCOME_TEXT = """ကြိုဆိုပါတယ်ရှင့်🙏🏻

📌ဘောနပ်စ်——
🎁အကောင့်ဖွင့်ပြီး 10,000ကျပ်ထိဖရီးယူ

⭐️ငွေသွင်း/ငွေထုတ် ချက်ချင်းရ
⭐️RTP 97% | နိုင်ခြေအမြင့်ဆုံး
✅တရားဝင် လိုင်စင်ရပြီး

App ဒေါင်းရန်👇👇👇"""
GAME_LINK_TEXT = "🔗 ဂိမ်းတိုက်ရိုက်လင့် \nhttps://j777ml.com"
APK_PATH = Path(__file__).resolve().parent.parent / "assets" / "J777-v1.0.3.apk"
OWNER_ID = 5168675744
COPYABLE_FIELDS = (
    "text", "animation", "audio", "contact", "dice", "document", "live_photo",
    "location", "photo", "sticker", "venue", "video", "video_note", "voice",
)

def connect_database(database_url):
    return psycopg.connect(database_url, connect_timeout=10, prepare_threshold=None)


def update_welcome(database_url, action, message_id):
    with connect_database(database_url) as connection:
        if action == "start":
            connection.execute(
                "INSERT INTO public.telegram_welcome (owner_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (OWNER_ID,),
            )

        state = connection.execute(
            """SELECT draft_started, editing, draft_ids, published_from, published_to, published_ids
               FROM public.telegram_welcome WHERE owner_id = %s FOR UPDATE""",
            (OWNER_ID,),
        ).fetchone()
        if state is None:
            return "no_draft" if action == "done" else None

        started, editing, draft, published_from, published_to, published = state
        if action == "start":
            if message_id > started:
                connection.execute(
                    """UPDATE public.telegram_welcome SET draft_started = %s, editing = true, draft_ids = '{}'
                       WHERE owner_id = %s""",
                    (message_id, OWNER_ID),
                )
                return "started"
            return "started" if message_id == started and editing else None

        if action == "done":
            if message_id == published_to:
                return "published"
            if not editing or message_id <= started:
                return "no_draft"
            ready = [item for item in draft if item < message_id]
            if not ready:
                return "empty"
            connection.execute(
                """UPDATE public.telegram_welcome
                   SET editing = false, draft_ids = '{}', published_from = draft_started,
                       published_to = %s, published_ids = %s
                   WHERE owner_id = %s""",
                (message_id, ready, OWNER_ID),
            )
            return "published"

        if editing and message_id > started and message_id not in draft:
            connection.execute(
                "UPDATE public.telegram_welcome SET draft_ids = %s WHERE owner_id = %s",
                (sorted([*draft, message_id]), OWNER_ID),
            )
        elif published_from < message_id < published_to and message_id not in published:
            # Telegram can deliver a message sent before /done after the publish transaction.
            connection.execute(
                "UPDATE public.telegram_welcome SET published_ids = %s WHERE owner_id = %s",
                (sorted([*published, message_id]), OWNER_ID),
            )


def send_telegram(bot_token, method, body, content_type="application/json"):
    request = Request(
        f"https://api.telegram.org/bot{bot_token}/{method}",
        data=body,
        headers={"Content-Type": content_type},
    )
    with urlopen(request, timeout=8):
        pass


def send_message(bot_token, chat_id, text):
    send_telegram(bot_token, "sendMessage", json.dumps({"chat_id": chat_id, "text": text}).encode())


def edit_welcome(bot_token, chat_id, message, command, database_url):
    if command in ("/setwelcome", "/done"):
        if not database_url:
            send_message(bot_token, chat_id, "Connect Neon to the Vercel project first.")
            return
        action = "start" if command == "/setwelcome" else "done"
    elif database_url and any(field in message for field in COPYABLE_FIELDS):
        action = "add"
    else:
        return

    result = update_welcome(database_url, action, message["message_id"])
    replies = {
        "started": "Send the welcome messages in order, then send /done to publish them.",
        "published": "Welcome updated. Send /start to preview it.",
        "empty": "Send at least one welcome message, then send /done again.",
        "no_draft": "Send /setwelcome to start a new welcome.",
    }
    if result in replies:
        send_message(bot_token, chat_id, replies[result])


def send_saved_welcome(bot_token, chat_id, database_url):
    if not database_url:
        return False

    with connect_database(database_url) as connection:
        row = connection.execute(
            "SELECT published_ids FROM public.telegram_welcome WHERE owner_id = %s", (OWNER_ID,)
        ).fetchone()
    if row is None:
        return False

    messages = row[0]
    for start in range(0, len(messages), 100):
        body = {
            "chat_id": chat_id,
            "from_chat_id": OWNER_ID,
            "message_ids": messages[start:start + 100],
        }
        send_telegram(bot_token, "copyMessages", json.dumps(body).encode())
    return bool(messages)


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

    send_message(bot_token, chat_id, WELCOME_TEXT)
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
        if chat.get("type") == "private":
            words = message.get("text", "").split(maxsplit=1)
            command = words[0] if words else ""
            database_url = os.environ.get("DATABASE_URL")
            try:
                if command == "/start":
                    if not send_saved_welcome(bot_token, chat["id"], database_url):
                        send_start_messages(bot_token, chat["id"])
                elif message.get("from", {}).get("id") == OWNER_ID:
                    edit_welcome(bot_token, chat["id"], message, command, database_url)
            except psycopg.Error:
                self.send_error(502, "Welcome database is unavailable")
                return
            except (URLError, TimeoutError) as error:
                if getattr(error, "code", None) != 403:
                    self.send_error(502, "Telegram could not deliver the reply")
                    return

        self.send_response(204)
        self.end_headers()
