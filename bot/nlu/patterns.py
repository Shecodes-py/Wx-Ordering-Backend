"""
Intent-detection patterns and keyword sets.

detect_intent() returns one of:
    ADD_ITEM | REMOVE_ITEM | VIEW_MENU | VIEW_CART | PROCEED_TO_CHECKOUT |
    PROVIDE_NOTES | PROVIDE_ADDRESS | SELECT_PAYMENT_METHOD |
    CONFIRM_ORDER | CANCEL | GENERAL_CHAT
"""
import re

# ---------------------------------------------------------------------------
# Keyword sets (extend these as you learn what customers say)
# ---------------------------------------------------------------------------

GREET = {
    'hi', 'hello', 'hey', 'start', 'restart', 'hii', 'helo',
    'good morning', 'good afternoon', 'good evening', 'yo', 'sup',
}

MENU_TRIGGERS = {
    'menu', 'show menu', 'what do you have', 'what do you sell',
    'what can i order', 'whats available', "what's available",
    'show me', 'options', 'food', 'list', 'see menu',
    'send menu', 'your menu', 'items',
}

CART_TRIGGERS = {
    'cart', 'bag', 'basket', 'my order', 'what did i add',
    'show cart', 'show order', 'my cart', 'current order',
    'what i ordered', 'my items',
}

CHECKOUT_TRIGGERS = {
    'done', 'checkout', 'check out', "that's all", "that's it",
    'thats all', 'thats it', 'order now', 'place order', 'confirm order',
    'ready', "i'm done", 'im done', 'proceed', 'finish', 'complete',
    'go ahead', 'submit', 'finalize', 'i want to order',
}

REMOVE_VERBS = re.compile(
    r'\b(remove|take out|delete|drop|cancel|ditch|no more|less|minus)\b',
    re.I,
)

CANCEL_TRIGGERS = {
    'cancel', 'nevermind', 'never mind', 'start over', 'reset',
    'scratch that', 'abort', 'forget it', 'clear cart', 'empty cart',
    'discard', 'restart order',
}

CONFIRM_YES = {
    'yes', 'yeah', 'yep', 'yup', 'confirm', 'ok', 'okay',
    'sure', 'go ahead', 'looks good', 'correct', 'perfect',
    'proceed', 'place it', 'send it', 'do it', 'right', 'aye',
    'alright', 'exactly', 'absolutely', 'affirmative', 'confirmed',
}

CONFIRM_NO = {
    'no', 'nope', 'nah', 'wait', 'hold on', 'change', 'edit',
    'modify', 'not yet', 'wrong', 'actually', 'different',
}

NOTES_NONE = {
    'none', 'nothing', 'no', 'nope', 'no thanks', 'all good',
    'no instructions', 'no notes', 'no special', 'nothing special',
    'no preference', 'normal', 'regular', 'standard',
}

TRANSFER_KEYWORDS = {
    'transfer', 'bank transfer', 'bank', 'pay online', 'online payment',
    '1', 'option 1', 'wire', 'account',
}

POD_KEYWORDS = {
    'delivery', 'pay on delivery', 'pod', 'cash', 'cash on delivery',
    'cod', '2', 'option 2', 'pay when', 'pay at door', 'pay at delivery',
}

# ---------------------------------------------------------------------------
# Quantity words
# ---------------------------------------------------------------------------

WORD_TO_NUM = {
    'a': 1, 'an': 1, 'one': 1,
    'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'half a dozen': 6, 'dozen': 12,
}

# Matches "3", "two", "a" before an item name
QTY_PATTERN = re.compile(
    r'\b(\d+|a\b|an\b|one|two|three|four|five|six|seven|eight|nine|ten|dozen)\b',
    re.I,
)

# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase, collapse whitespace."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def detect_intent(msg: str, state: str, cart: dict, session=None) -> str:
    """
    Determine the customer's intent given their message and current session state.
    State-aware: the same word can mean different things at different steps.
    """
    m = _norm(msg)

    # Greeting / restart — always valid anywhere
    if m in GREET or set(m.split()).issubset(GREET):
        return 'VIEW_MENU'

    # Cancel — always valid
    if m in CANCEL_TRIGGERS or any(t in m for t in CANCEL_TRIGGERS):
        return 'CANCEL'

    # ---- CONFIRMATION sub-flow ----------------------------------------
    # Once the customer is in checkout, interpret messages as checkout answers
    if state == 'CONFIRMATION':
        return _detect_confirmation_intent(m, session)

    # ---- ORDERING / general flow --------------------------------------

    # Cart view
    if any(t in m for t in CART_TRIGGERS):
        return 'VIEW_CART'

    # Menu view
    if m in MENU_TRIGGERS or any(t in m for t in MENU_TRIGGERS):
        return 'VIEW_MENU'

    # Checkout
    if m in CHECKOUT_TRIGGERS or any(t in m for t in CHECKOUT_TRIGGERS):
        return 'PROCEED_TO_CHECKOUT'

    # Remove item
    if REMOVE_VERBS.search(m):
        return 'REMOVE_ITEM'

    # If we have a number or item-like word → likely ADD_ITEM (entity extraction confirms)
    # This is a soft signal; the extractor will validate against the live menu.
    if QTY_PATTERN.search(m):
        return 'ADD_ITEM'

    # In ORDERING state, assume anything with content is an item request
    if state == 'ORDERING' and len(m) > 2:
        return 'ADD_ITEM'

    return 'GENERAL_CHAT'


def _detect_confirmation_intent(m: str, session) -> str:
    """
    Inside the CONFIRMATION state, interpret message based on what's still missing.
    """
    # notes is None = not yet asked; '' = asked but no instructions; str = actual notes
    notes_set   = session is not None and session.notes is not None
    address_set = bool(session and session.extracted_address)
    payment_set = bool(session and session.payment_method)

    # --- Step 1: collecting notes ---
    if not notes_set:
        return 'PROVIDE_NOTES'

    # --- Step 2: collecting address ---
    if not address_set:
        return 'PROVIDE_ADDRESS'

    # --- Step 3: collecting payment method ---
    if not payment_set:
        if m in TRANSFER_KEYWORDS or any(k in m for k in TRANSFER_KEYWORDS):
            return 'SELECT_PAYMENT_METHOD'
        if m in POD_KEYWORDS or any(k in m for k in POD_KEYWORDS):
            return 'SELECT_PAYMENT_METHOD'
        # Ambiguous — treat as payment selection attempt
        return 'SELECT_PAYMENT_METHOD'

    # --- Step 4: final yes/no ---
    if m in CONFIRM_YES or any(k in m for k in CONFIRM_YES):
        return 'CONFIRM_ORDER'
    if m in CONFIRM_NO or any(k in m for k in CONFIRM_NO):
        return 'CONFIRM_ORDER'  # is_confirmed=False handled in extractor

    return 'CONFIRM_ORDER'
