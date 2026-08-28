"""
Interactive NLU tester — no database, no Django server needed.

Usage:
    python test_nlu.py

Type a customer message, see what the engine returns.
Type 'quit' to exit, 'reset' to start a fresh session.
"""
import sys
import os

# Add project root to path so imports work
sys.path.insert(0, os.path.dirname(__file__))

# Minimal Django setup (settings-free)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# We bypass Django entirely — just import the NLU modules directly
from bot.nlu.patterns import detect_intent
from bot.nlu.extractor import extract_entities
from bot.nlu.engine import process_message


# ---------------------------------------------------------------------------
# Mock objects (stand-ins for DB models)
# ---------------------------------------------------------------------------

class MockItem:
    def __init__(self, id, name, description, price, is_available=True):
        self.id = id
        self.name = name
        self.description = description
        self.price = price
        self.is_available = is_available


class MockProfile:
    def __init__(self):
        self.full_name = "Test User"
        self.delivery_address = "12 Adeola Odeku, Victoria Island"
        self.phone_number = "+2348000000000"

    def save(self, update_fields=None):
        pass  # no-op


class MockSession:
    def __init__(self):
        self.state = 'START'
        self.cart = {}
        self.notes = ''
        self.extracted_address = ''
        self.payment_method = ''

    @property
    def profile(self):
        return _profile

    def save(self, update_fields=None):
        pass

    def reset(self):
        self.state = 'START'
        self.cart = {}
        self.notes = ''
        self.extracted_address = ''
        self.payment_method = ''


# ---------------------------------------------------------------------------
# Sample menu — edit to match your real items
# ---------------------------------------------------------------------------

MENU = [
    MockItem(1,  "Jollof Rice",         "Nigerian party jollof",                  1500),
    MockItem(2,  "Fried Rice",          "Stir-fried with veggies and spices",      1500),
    MockItem(3,  "Grilled Chicken",     "Half chicken, smoky marinade",            2500),
    MockItem(4,  "Fried Chicken",       "Crispy southern-style",                   2000),
    MockItem(5,  "Puff Puff",           "Deep-fried Nigerian doughnuts (5 pcs)",    500),
    MockItem(6,  "Coca-Cola 330ml",     "Chilled coke",                             300),
    MockItem(7,  "Water 75cl",          "Eva still water",                          200),
    MockItem(8,  "Peppered Snail",      "Slow-cooked in tomato pepper sauce",      3500),
    MockItem(9,  "Moi Moi",            "Steamed bean pudding",                      800),
    MockItem(10, "Plantain (Dodo)",     "Sweet fried ripe plantain",               600),
]

_profile = MockProfile()
_session = MockSession()


# ---------------------------------------------------------------------------
# Simulate what views.py does with the returned dict
# ---------------------------------------------------------------------------

def apply_intent(intent_data: dict, session: MockSession, profile: MockProfile):
    """Mirror the dispatch logic from views.py so the session state updates."""
    intent = intent_data['intent']
    menu_map = {item.id: item for item in MENU}

    if intent_data.get('extracted_notes') is not None:
        session.notes = intent_data['extracted_notes']

    if intent_data.get('extracted_address') is not None:
        session.extracted_address = intent_data['extracted_address']
        profile.delivery_address = intent_data['extracted_address']

    if intent_data.get('extracted_payment_method') is not None:
        session.payment_method = intent_data['extracted_payment_method']

    if intent == 'ADD_ITEM':
        for it in intent_data.get('items', []):
            iid = it.get('matched_menu_id')
            qty = it.get('quantity', 1)
            if iid:
                session.cart[str(iid)] = session.cart.get(str(iid), 0) + qty
        if session.state == 'START':
            session.state = 'ORDERING'

    elif intent == 'REMOVE_ITEM':
        for it in intent_data.get('items', []):
            iid = str(it.get('matched_menu_id', ''))
            qty = it.get('quantity', 1)
            if iid in session.cart:
                session.cart[iid] = max(0, session.cart[iid] - qty)
                if session.cart[iid] == 0:
                    del session.cart[iid]

    elif intent in ('VIEW_MENU',):
        if session.state == 'START':
            session.state = 'ORDERING'

    elif intent in ('PROCEED_TO_CHECKOUT', 'PROVIDE_NOTES',
                    'PROVIDE_ADDRESS', 'SELECT_PAYMENT_METHOD'):
        session.state = 'CONFIRMATION'

    elif intent == 'CONFIRM_ORDER':
        if intent_data.get('is_confirmed'):
            print("\n  ✅ [Order would be created here — resetting session]")
            session.reset()
            return
        else:
            session.state = 'ORDERING'

    elif intent == 'CANCEL':
        session.reset()


def print_session(session: MockSession):
    menu_map = {item.id: item for item in MENU}
    cart_display = {
        menu_map[int(k)].name: v
        for k, v in session.cart.items()
        if int(k) in menu_map
    } if session.cart else {}

    print(f"\n  📦 State: {session.state}")
    print(f"  🛒 Cart:  {cart_display or 'empty'}")
    if session.notes:
        print(f"  📝 Notes: {session.notes}")
    if session.extracted_address:
        print(f"  📍 Address: {session.extracted_address}")
    if session.payment_method:
        print(f"  💳 Payment: {session.payment_method}")


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

DIVIDER = "─" * 60

def run():
    print(DIVIDER)
    print("  WX NLU Interactive Tester")
    print(DIVIDER)
    print("  Menu items loaded:", len(MENU))
    print("  Profile name:", _profile.full_name)
    print("  Saved address:", _profile.delivery_address)
    print()
    print("  Commands:")
    print("    'reset'   — start a fresh session")
    print("    'menu'    — show the mock menu")
    print("    'session' — show current session state")
    print("    'quit'    — exit")
    print(DIVIDER)
    print()

    while True:
        try:
            msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not msg:
            continue

        if msg.lower() == 'quit':
            print("Bye!")
            break

        if msg.lower() == 'reset':
            _session.reset()
            print("  ↩ Session reset.\n")
            continue

        if msg.lower() == 'menu':
            print()
            for i, item in enumerate(MENU, 1):
                print(f"  {i}. {item.name} — ₦{item.price:,}")
            print()
            continue

        if msg.lower() == 'session':
            print_session(_session)
            print()
            continue

        # Run the NLU engine
        result = process_message(MENU, _profile, _session, msg)

        # Print structured result
        print()
        print(f"  Intent:  {result['intent']}")
        if result['items']:
            for it in result['items']:
                print(f"  Item:    {it['quantity']}× {it['item_name']} (id={it['matched_menu_id']})")
        if result['extracted_notes'] is not None:
            print(f"  Notes:   {result['extracted_notes'] or '(none)'}")
        if result['extracted_address']:
            print(f"  Address: {result['extracted_address']}")
        if result['extracted_payment_method']:
            print(f"  Payment: {result['extracted_payment_method']}")
        if result['is_confirmed'] is not None:
            print(f"  Confirmed: {result['is_confirmed']}")

        # Apply the intent so session updates
        apply_intent(result, _session, _profile)

        # Show the bot's reply
        print()
        reply = result['reply_message']
        for line in reply.split('\n'):
            print(f"  Bot: {line}")

        print_session(_session)
        print()


if __name__ == '__main__':
    run()
