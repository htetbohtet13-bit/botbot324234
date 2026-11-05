import json
import re
import sys
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def check_connection(webhook_url, token, secret):
    for method in ("getMe", "getWebhookInfo"):
        try:
            with urlopen(Request(f"https://api.telegram.org/bot{token}/{method}", data=b"{}"), timeout=15) as response:
                result = json.load(response)
        except (URLError, TimeoutError, ValueError):
            raise SystemExit(f"Could not read Telegram {method}. Check the bot token and network connection.") from None
        if not result.get("ok"):
            raise SystemExit(f"Telegram did not confirm {method}.")
        if method == "getMe":
            bot = result["result"]
            print(f"Token belongs to @{bot.get('username')} (ID {bot['id']}).")
        else:
            info = result["result"]
            webhook = (info.get("url") or "not registered").replace(token, "[redacted]").replace(secret, "[redacted]")
            error = info.get("last_error_message", "none").replace(token, "[redacted]").replace(secret, "[redacted]")
            print("Webhook URL:", webhook)
            print("Pending updates:", info.get("pending_update_count", 0))
            print("Last delivery error:", error)

    request = Request(
        webhook_url, data=b'{"diagnostic":true}',
        headers={"Content-Type": "application/json", "X-Telegram-Bot-Api-Secret-Token": secret},
    )
    try:
        with urlopen(request, timeout=30) as response:
            if response.status == 204:
                raise SystemExit("Deploy the latest bot code to enable the Vercel configuration check.")
            report = json.load(response)
    except HTTPError as error:
        if error.code == 403:
            raise SystemExit("Vercel rejected the webhook secret. Check TELEGRAM_WEBHOOK_SECRET in Production and redeploy.") from None
        raise SystemExit(f"Vercel configuration check failed (HTTP {error.code}). Check its runtime logs.") from None
    except (URLError, TimeoutError, ValueError):
        raise SystemExit("Could not read the Vercel configuration check.") from None

    print(f"Vercel is running @{report.get('bot_username')} (ID {report.get('bot_id')}).")
    if report.get("bot_id") != bot["id"]:
        print("TOKEN MISMATCH. Update TELEGRAM_BOT_TOKEN in Vercel Production and redeploy.")
    print("Neon:", report.get("database"))
    if report.get("missing_tables"):
        print("Missing tables:", ", ".join(report["missing_tables"]))


def main():
    args = sys.argv[1:]
    check_only = args[:1] == ["--check"]
    if check_only:
        args = args[1:]
    if len(args) != 1:
        raise SystemExit("Usage: py connect_telegram.py [--check] https://YOUR-PROJECT.vercel.app/api/telegram")

    webhook_url = args[0]
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

    if check_only:
        check_connection(webhook_url, token, secret)
        return

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
