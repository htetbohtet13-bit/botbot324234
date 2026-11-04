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
OWNER_ID = 5168675744
EDITOR_KEY = "{telegram-welcome}:editor"
DRAFT_KEY = "{telegram-welcome}:draft"
PUBLISHED_KEY = "{telegram-welcome}:published"
COPYABLE_FIELDS = (
    "text", "animation", "audio", "contact", "dice", "document", "live_photo",
    "location", "photo", "sticker", "venue", "video", "video_note", "voice",
)

# Change the draft and published sequence atomically across webhook invocations.
# Telegram can deliver updates concurrently, so order each sequence by message ID.
EDIT_WELCOME = """
local editor, draft, published = unpack(KEYS)
local action, message = ARGV[1], ARGV[2]
local id = tonumber(message)
local started = tonumber(redis.call('HGET', editor, 'started')) or 0
local editing = redis.call('HGET', editor, 'editing') == '1'
local published_from = tonumber(redis.call('HGET', editor, 'published_from')) or 0
local published_to = tonumber(redis.call('HGET', editor, 'published_to')) or 0

if action == 'start' then
    if id > started then
        redis.call('DEL', draft)
        redis.call('HSET', editor, 'started', message, 'editing', '1')
        return 'started'
    end
    if id == started and editing then return 'started' end
elseif action == 'done' then
    if id == published_to then return 'published' end
    if not editing or id <= started then return 'no_draft' end
    if redis.call('ZCOUNT', draft, '-inf', '(' .. message) == 0 then
        return 'empty'
    end
    redis.call('ZREMRANGEBYSCORE', draft, message, '+inf')
    redis.call('RENAME', draft, published)
    redis.call('HSET', editor, 'editing', '0', 'published_from', started, 'published_to', message)
    return 'published'
elseif editing and id > started then
    redis.call('ZADD', draft, id, message)
elseif id > published_from and id < published_to then
    -- Include messages sent before /done that reached the webhook just after it.
    redis.call('ZADD', published, id, message)
end
return ''
"""


class WelcomeStoreError(Exception):
    pass


def redis_settings():
    for url_key, token_key in (
        ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"),
        ("KV_REST_API_URL", "KV_REST_API_TOKEN"),
    ):
        url, token = os.environ.get(url_key), os.environ.get(token_key)
        if url and token:
            return url, token
    return None


def redis_command(settings, *command):
    url, token = settings
    request = Request(
        url,
        data=json.dumps(command).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            result = json.load(response)
    except (OSError, ValueError):
        raise WelcomeStoreError from None
    if "result" not in result:
        raise WelcomeStoreError
    return result["result"]


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


def edit_welcome(bot_token, chat_id, message, command, settings):
    if command in ("/setwelcome", "/done"):
        if not settings:
            send_message(bot_token, chat_id, "Connect the welcome database in Vercel first.")
            return
        action = "start" if command == "/setwelcome" else "done"
    elif settings and any(field in message for field in COPYABLE_FIELDS):
        action = "add"
    else:
        return

    result = redis_command(
        settings, "EVAL", EDIT_WELCOME, 3, EDITOR_KEY, DRAFT_KEY, PUBLISHED_KEY,
        action, str(message["message_id"]),
    )
    replies = {
        "started": "Send the welcome messages in order, then send /done to publish them.",
        "published": "Welcome updated. Send /start to preview it.",
        "empty": "Send at least one welcome message, then send /done again.",
        "no_draft": "Send /setwelcome to start a new welcome.",
    }
    if result in replies:
        send_message(bot_token, chat_id, replies[result])


def send_saved_welcome(bot_token, chat_id, settings):
    if not settings:
        return False

    messages = redis_command(settings, "ZRANGE", PUBLISHED_KEY, 0, -1)
    for start in range(0, len(messages), 100):
        body = {
            "chat_id": chat_id,
            "from_chat_id": OWNER_ID,
            "message_ids": [int(message) for message in messages[start:start + 100]],
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
            settings = redis_settings()
            try:
                if command == "/start":
                    if not send_saved_welcome(bot_token, chat["id"], settings):
                        send_start_messages(bot_token, chat["id"])
                elif message.get("from", {}).get("id") == OWNER_ID:
                    edit_welcome(bot_token, chat["id"], message, command, settings)
            except WelcomeStoreError:
                self.send_error(502, "Welcome database is unavailable")
                return
            except (URLError, TimeoutError) as error:
                if getattr(error, "code", None) != 403:
                    self.send_error(502, "Telegram could not deliver the reply")
                    return

        self.send_response(204)
        self.end_headers()
