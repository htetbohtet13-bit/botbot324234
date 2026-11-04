import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from secrets import token_hex
from time import sleep
from urllib.error import HTTPError, URLError
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


def update_welcome(connection, action, message_id):
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


def send_message(bot_token, chat_id, text, reply_markup=None):
    body = {"chat_id": chat_id, "text": text}
    if reply_markup:
        body["reply_markup"] = reply_markup
    send_telegram(bot_token, "sendMessage", json.dumps(body).encode())


def copy_messages(bot_token, chat_id, source_chat_id, message_ids):
    for start in range(0, len(message_ids), 100):
        body = {
            "chat_id": chat_id,
            "from_chat_id": source_chat_id,
            "message_ids": message_ids[start:start + 100],
        }
        send_telegram(bot_token, "copyMessages", json.dumps(body).encode())


def edit_welcome(connection, message_id, command):
    action = {"/setwelcome": "start", "/done": "done"}.get(command, "add")
    result = update_welcome(connection, action, message_id)
    replies = {
        "started": "Send the welcome messages in order, then send /done to publish them.",
        "published": "Welcome updated. Send /start to preview it.",
        "empty": "Send at least one welcome message, then send /done again.",
        "no_draft": "Send /setwelcome to start a new welcome.",
    }
    return replies.get(result)


def load_menu_buttons(connection):
    return connection.execute("SELECT id, label FROM public.telegram_menu_buttons ORDER BY id").fetchall()


def send_menu(bot_token, chat_id, buttons):
    for start in range(0, len(buttons), 50):
        keyboard = [
            [{"text": label, "callback_data": f"menu:{button_id}"}]
            for button_id, label in buttons[start:start + 50]
        ]
        send_message(bot_token, chat_id, "Choose an option", {"inline_keyboard": keyboard})


def show_menu(bot_token, chat_id, database_url):
    buttons = []
    if database_url:
        with connect_database(database_url) as connection:
            buttons = load_menu_buttons(connection)
    if buttons:
        send_menu(bot_token, chat_id, buttons)
    else:
        send_message(bot_token, chat_id, "There are no menu buttons yet.")


def save_menu_button(connection, label, message_date, update_id, *, reply_text="", source=None):
    chat_id, started, finished, message_ids = source or (None, None, None, [])
    result = connection.execute(
        """INSERT INTO public.telegram_menu_buttons AS button
               (label, reply_text, updated_at, update_id, source_chat_id, source_started_message_id,
                source_done_message_id, message_ids)
           VALUES (%s, %s, to_timestamp(%s), %s, %s, %s, %s, %s)
           ON CONFLICT (label) DO UPDATE SET reply_text = EXCLUDED.reply_text,
               updated_at = EXCLUDED.updated_at, update_id = EXCLUDED.update_id,
               source_chat_id = EXCLUDED.source_chat_id,
               source_started_message_id = EXCLUDED.source_started_message_id,
               source_done_message_id = EXCLUDED.source_done_message_id, message_ids = EXCLUDED.message_ids
           WHERE (button.updated_at, button.update_id) <= (EXCLUDED.updated_at, EXCLUDED.update_id)""",
        (label, reply_text, message_date, update_id, chat_id, started, finished, message_ids),
    )
    if result.rowcount == 1:
        return f"Saved the {label} button. Send /menu to try it."
    return f"The {label} button already has a newer reply."


def add_menu_button(connection, chat_id, message, update_id, draft, is_owner):
    first_line, _, reply_text = message["text"].partition("\n")
    heading = first_line.split(maxsplit=1)
    label = heading[1].strip() if len(heading) > 1 else ""
    if not label:
        return "Send /addmenu Support, then send the button's messages and finish with /done."
    if len(label) > 64:
        return "Use a button label with at most 64 characters."
    if reply_text.strip():
        return save_menu_button(connection, label, message["date"], update_id, reply_text=reply_text)

    message_id = message["message_id"]
    if is_owner:
        welcome = connection.execute(
            "SELECT draft_started, editing FROM public.telegram_welcome WHERE owner_id = %s", (OWNER_ID,)
        ).fetchone()
        if welcome and message_id <= welcome[0]:
            return None
        if welcome and welcome[1]:
            return "Finish editing the welcome with /done before starting a button draft."

    if draft and message_id <= (draft[2] or draft[1]):
        if message_id != draft[1] or draft[2] is not None:
            return None
    else:
        connection.execute(
            """INSERT INTO public.telegram_menu_drafts (chat_id, label, started_message_id) VALUES (%s, %s, %s)
               ON CONFLICT (chat_id) DO UPDATE SET label = EXCLUDED.label,
                   started_message_id = EXCLUDED.started_message_id, done_message_id = NULL, message_ids = '{}'""",
            (chat_id, label, message_id),
        )
    return f"Send the messages for {label} in order, then send /done."


def update_menu_draft(connection, chat_id, message, update_id, command, draft):
    message_id = message["message_id"]
    if draft:
        label, started, finished, message_ids = draft
        if command == "/done" and message_id == finished:
            return True, f"Finished editing the {label} button. Send /menu to try it."
        if finished is None and message_id > started:
            if command == "/done":
                ready = [item for item in message_ids if item < message_id]
                if not ready:
                    return True, "Send at least one message for the button, then send /done again."
                reply = save_menu_button(
                    connection, label, message["date"], update_id, source=(chat_id, started, message_id, ready)
                )
                connection.execute(
                    "UPDATE public.telegram_menu_drafts SET done_message_id = %s, message_ids = '{}' WHERE chat_id = %s",
                    (message_id, chat_id),
                )
                return True, reply
            if message_id not in message_ids:
                connection.execute(
                    "UPDATE public.telegram_menu_drafts SET message_ids = %s WHERE chat_id = %s",
                    (sorted([*message_ids, message_id]), chat_id),
                )
            return True, None

    if command == "/done":
        return False, None

    # Include earlier content that Telegram delivered after the matching /done.
    result = connection.execute(
        """UPDATE public.telegram_menu_buttons AS button SET message_ids = ARRAY(
               SELECT DISTINCT item FROM unnest(array_append(button.message_ids, %s)) AS entries(item) ORDER BY item
           ) WHERE source_chat_id = %s AND source_started_message_id < %s AND source_done_message_id > %s""",
        (message_id, chat_id, message_id, message_id),
    )
    return result.rowcount > 0, None


def edit_admin(bot_token, chat_id, message, update_id, command, database_url, is_owner):
    edit_commands = ("/addmenu", "/setwelcome", "/done")
    if command not in edit_commands and not any(field in message for field in COPYABLE_FIELDS):
        return
    if not database_url:
        if command in edit_commands:
            send_message(bot_token, chat_id, "Connect Neon to the Vercel project first.")
        return

    with connect_database(database_url) as connection:
        # Serialize edits in this admin's chat, including switching between welcome and menu drafts.
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (chat_id,))
        draft = connection.execute(
            """SELECT label, started_message_id, done_message_id, message_ids
               FROM public.telegram_menu_drafts WHERE chat_id = %s""",
            (chat_id,),
        ).fetchone()
        if command == "/addmenu":
            reply = add_menu_button(connection, chat_id, message, update_id, draft, is_owner)
        elif command == "/setwelcome":
            if draft and message["message_id"] <= (draft[2] or draft[1]):
                reply = None
            elif draft and draft[2] is None:
                reply = "Finish the button draft with /done before editing the welcome."
            else:
                reply = edit_welcome(connection, message["message_id"], command)
        else:
            handled, reply = update_menu_draft(connection, chat_id, message, update_id, command, draft)
            if not handled and is_owner:
                reply = edit_welcome(connection, message["message_id"], command)
            elif not handled and command == "/done":
                reply = "Send /addmenu followed by a button name to start a draft."
    if reply:
        send_message(bot_token, chat_id, reply)


def handle_menu_callback(bot_token, callback, database_url):
    data = callback.get("data", "")
    chat = callback.get("message", {}).get("chat", {})
    if chat.get("type") != "private" or not data.startswith("menu:"):
        return

    try:
        send_telegram(bot_token, "answerCallbackQuery", json.dumps({"callback_query_id": callback["id"]}).encode())
    except HTTPError as error:
        if error.code != 400:
            raise

    button_id = data.removeprefix("menu:")
    if not (button_id.isascii() and button_id.isdecimal() and len(button_id) <= 19):
        return
    button_id = int(button_id)
    if not 0 < button_id <= 2**63 - 1:
        return

    row = None
    if database_url:
        with connect_database(database_url) as connection:
            row = connection.execute(
                "SELECT reply_text, source_chat_id, message_ids FROM public.telegram_menu_buttons WHERE id = %s",
                (button_id,),
            ).fetchone()
    if row and row[2]:
        copy_messages(bot_token, chat["id"], row[1], row[2])
    else:
        reply = row[0] if row else "That button is unavailable. Send /menu to refresh."
        send_message(bot_token, chat["id"], reply)


def handle_start(bot_token, chat_id, message_date, database_url):
    messages = []
    buttons = []
    if database_url:
        with connect_database(database_url) as connection:
            connection.execute(
                """INSERT INTO public.telegram_subscribers AS subscriber
                       (chat_id, first_started_at, last_started_at)
                   VALUES (%s, to_timestamp(%s), to_timestamp(%s))
                   ON CONFLICT (chat_id) DO UPDATE SET
                       first_started_at = LEAST(subscriber.first_started_at, EXCLUDED.first_started_at),
                       last_started_at = GREATEST(subscriber.last_started_at, EXCLUDED.last_started_at)""",
                (chat_id, message_date, message_date),
            )
            row = connection.execute(
                "SELECT published_ids FROM public.telegram_welcome WHERE owner_id = %s", (OWNER_ID,)
            ).fetchone()
            buttons = load_menu_buttons(connection)
        if row:
            messages = row[0]

    if not messages:
        send_start_messages(bot_token, chat_id)
    else:
        copy_messages(bot_token, chat_id, OWNER_ID, messages)
    if buttons:
        sleep(1)
        send_menu(bot_token, chat_id, buttons)


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


def handle_update(bot_token, update, database_url):
    if "callback_query" in update:
        handle_menu_callback(bot_token, update["callback_query"], database_url)
        return

    message = update.get("message", {})
    chat = message.get("chat", {})
    if chat.get("type") != "private":
        return

    words = message.get("text", "").split(maxsplit=1)
    command = words[0] if words else ""
    user_id = message.get("from", {}).get("id")
    chat_id = chat["id"]
    if command == "/start":
        handle_start(bot_token, chat_id, message["date"], database_url)
    elif command == "/menu":
        show_menu(bot_token, chat_id, database_url)
    else:
        is_owner = user_id == OWNER_ID
        admin_ids = {item.strip() for item in os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",")}
        if command == "/setwelcome" and not is_owner:
            return
        if is_owner or (user_id is not None and str(user_id) in admin_ids):
            edit_admin(bot_token, chat_id, message, update["update_id"], command, database_url, is_owner)


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

        try:
            handle_update(bot_token, update, os.environ.get("DATABASE_URL"))
        except psycopg.Error:
            self.send_error(502, "Bot database is unavailable")
            return
        except (URLError, TimeoutError) as error:
            if getattr(error, "code", None) != 403:
                self.send_error(502, "Telegram could not deliver the reply")
                return

        self.send_response(204)
        self.end_headers()
