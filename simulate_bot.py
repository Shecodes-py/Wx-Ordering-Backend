"""
Local bot simulator — full Django + real DB, zero Twilio.

Usage:
    python simulate_bot.py [phone_number]

    phone_number  optional, defaults to +2340000000001
                  use different numbers to test as different customers

What it does:
    • Sets up Django exactly as in production (reads your .env / DATABASE_URL)
    • Replaces send_whatsapp_message() with a local printer — no Twilio calls
    • Calls WhatsAppWebhookView._handle() directly, so every migration,
      model, session, and NLU path runs exactly as it would on the real server
    • Shows the bot reply + current session state after each turn

Type 'quit' to exit, 'reset' to wipe the session, 'state' to inspect it.
"""

import os
import sys

# ── 1. Django bootstrap ───────────────────────────────────────────────────────
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

# ── 2. Mock Twilio BEFORE any bot code is imported ───────────────────────────
# We patch bot.services.send_whatsapp_message so nothing hits Twilio.
import bot.services as _svc

_replies: list[str] = []   # collect replies printed this turn

def _mock_send(to: str, body: str):
    _replies.append(body)

_svc.send_whatsapp_message = _mock_send

# ── 3. Now import bot code (it will use the patched function) ─────────────────
from bot.views import WhatsAppWebhookView
from bot.models import BotSession
from profiles.models import Profile
from dashboard.models import MenuItem

# ── 4. Helpers ────────────────────────────────────────────────────────────────

DIVIDER     = "─" * 60
BOT_PREFIX  = "\033[92m  Bot:\033[0m "   # green
YOU_PREFIX  = "\033[94m  You:\033[0m "   # blue
INFO_PREFIX = "\033[90m      \033[0m"    # grey


def _print_reply(replies: list[str]):
    for msg in replies:
        for line in msg.split('\n'):
            print(f"{BOT_PREFIX}{line}")


def _print_state(phone: str):
    try:
        profile = Profile.objects.get(phone_number=phone)
        session = BotSession.objects.get(profile=profile)
        menu_map = {i.id: i for i in MenuItem.objects.filter(is_available=True)}
        cart_display = {
            menu_map[int(k)].name: v
            for k, v in session.cart.items()
            if int(k) in menu_map
        } if session.cart else {}
        print(f"{INFO_PREFIX}┌─ session ──────────────────────────")
        print(f"{INFO_PREFIX}│ state:   {session.state}")
        print(f"{INFO_PREFIX}│ cart:    {cart_display or 'empty'}")
        print(f"{INFO_PREFIX}│ notes:   {repr(session.notes)}")
        print(f"{INFO_PREFIX}│ address: {session.extracted_address or '—'}")
        print(f"{INFO_PREFIX}│ payment: {session.payment_method or '—'}")
        print(f"{INFO_PREFIX}│ name:    {profile.full_name or '—'}")
        print(f"{INFO_PREFIX}└────────────────────────────────────")
    except (Profile.DoesNotExist, BotSession.DoesNotExist):
        print(f"{INFO_PREFIX}(no session yet for {phone})")


def _reset_session(phone: str):
    try:
        profile = Profile.objects.get(phone_number=phone)
        session = BotSession.objects.get(profile=profile)
        session.reset()
        print(f"{INFO_PREFIX}Session reset for {phone}")
    except (Profile.DoesNotExist, BotSession.DoesNotExist):
        print(f"{INFO_PREFIX}No session to reset.")


def _show_menu():
    items = MenuItem.objects.filter(is_available=True).order_by('id')
    if not items:
        print(f"{INFO_PREFIX}(no available menu items — add some in Django admin)")
        return
    print(f"{INFO_PREFIX}── live menu ──")
    for i, item in enumerate(items, 1):
        print(f"{INFO_PREFIX}{i}. {item.name} — ₦{item.price:,.0f}")


# ── 5. REPL ───────────────────────────────────────────────────────────────────

def run(phone: str):
    view = WhatsAppWebhookView()

    print(DIVIDER)
    print("  WX Bot Simulator  (real DB · no Twilio)")
    print(DIVIDER)
    print(f"  Simulating customer: {phone}")
    print(f"  DB: {os.getenv('DATABASE_URL', 'sqlite / default')}")
    print()
    print("  Commands:  state · reset · menu · quit")
    print(DIVIDER)
    print()

    _show_menu()
    print()

    while True:
        try:
            msg = input(f"{YOU_PREFIX}").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not msg:
            continue

        cmd = msg.lower()

        if cmd == 'quit':
            print("Bye!")
            break
        if cmd == 'state':
            _print_state(phone)
            print()
            continue
        if cmd == 'reset':
            _reset_session(phone)
            print()
            continue
        if cmd == 'menu':
            _show_menu()
            print()
            continue

        # ── call the bot ──
        _replies.clear()

        try:
            view._handle(phone, msg)
        except Exception as exc:
            print(f"\033[91m  ERROR: {exc}\033[0m")
            import traceback
            traceback.print_exc()
            print()
            continue

        print()
        if _replies:
            _print_reply(_replies)
        else:
            print(f"{INFO_PREFIX}(bot sent no reply)")

        print()
        _print_state(phone)
        print()


if __name__ == '__main__':
    phone = sys.argv[1] if len(sys.argv) > 1 else '+2340000000001'
    run(phone)
