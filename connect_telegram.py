import json
import re
import sys
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: py connect_telegram.py https://YOUR-PROJECT.vercel.app/api/telegram")

    webhook_url = sys.argv[1]
    url = urlsplit(webhook_url)
    if url.scheme != "https" or not url.hostname or url.path != "/api/telegram":
        raise SystemExit("Use your public HTTPS production URL followed by /api/telegram.")

    try:
        with urlopen(webhook_url, timeout=15) as response:
            if response.read(64) != b"Telegram webhook is reachable.\n":
                raise SystemExit("The URL did not return the bot's webhook status message.")
    except (URLError, TimeoutError):
        raise SystemExit("The webhook URL could not be reached without signing in.") from None

    token = getpass("BotFather token: ").strip()
    secret = getpass("Vercel TELEGRAM_WEBHOOK_SECRET: ").strip()
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise SystemExit("The bot token format is invalid.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        raise SystemExit("The webhook secret must use letters, numbers, underscores, or hyphens.")

    request = Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=json.dumps(
            {"url": webhook_url, "secret_token": secret, "allowed_updates": ["message"]}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except HTTPError as error:
        raise SystemExit(f"Telegram rejected webhook registration (HTTP {error.code}).") from None
    except (URLError, TimeoutError):
        raise SystemExit("Telegram could not be reached. Try running this again.") from None

    if not result.get("ok"):
        raise SystemExit("Telegram did not confirm webhook registration.")
    print("Webhook registered. Open the bot in Telegram and send /start.")


if __name__ == "__main__":
    main()
