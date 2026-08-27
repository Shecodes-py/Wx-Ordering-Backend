import json
import logging

import google.generativeai as genai
from django.conf import settings
from twilio.rest import Client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Twilio helpers
# ---------------------------------------------------------------------------

def get_twilio_client():
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_whatsapp_message(to: str, body: str):
    """Send a WhatsApp message via Twilio. Raises on failure."""
    try:
        client = get_twilio_client()
        to_formatted = f'whatsapp:{to}' if not to.startswith('whatsapp:') else to
        message = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            to=to_formatted,
            body=body,
        )
        logger.info("WhatsApp sent → %s | sid=%s", to, message.sid)
        return message
    except Exception as exc:
        logger.error("WhatsApp send failed → %s: %s", to, exc)
        raise


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def notify_payment_confirmed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"✅ Payment confirmed for Order #{order.id}!\n\nYour order is now being prepared. We'll let you know when it's on the way! 🛵"
    )


def notify_order_completed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"🎉 Your Order #{order.id} is ready and on its way!\n\nThank you for ordering with us — enjoy your meal! 😋"
    )


# ---------------------------------------------------------------------------
# AI processing
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a warm, efficient food ordering assistant for WX Ordering — a restaurant that takes orders via WhatsApp.

Your goal is to guide customers naturally from browsing the menu to placing their order. Be conversational, friendly, and human. Never sound robotic or force rigid numbered inputs (except for the menu list itself).

---

## CONTEXT (provided each turn)

**Available Menu:**
{menu_json}

**Customer Profile:**
{customer_profile_json}

**Session State:** {session_state}
**Current Cart:** {cart_json}
**Special Notes Collected:** "{session_notes}"
**Delivery Address Collected:** "{session_address}"
**Payment Method Selected:** "{session_payment_method}"

**Customer's Latest Message:** "{user_message}"

---

## BEHAVIOR RULES

### 1. Flexible Item Recognition
- Match items by name (fuzzy), description, or menu number.
- "Two jollof and a coke" → match by name similarity.
- "Add items 1 and 3" → match by menu position.
- Plural, shorthand, and slight misspellings are fine (e.g. "chicken rice" → "Chicken Fried Rice").
- If something is ambiguous, ask a quick clarifying question.
- If an item is unavailable or not on the menu, say so gently and suggest alternatives.

### 2. Natural Conversation
- When state is START or the cart is empty, show the menu with emojis and prices.
- Confirm each addition warmly: "Got it! 2× Jollof Rice added 🍛. Anything else, or ready to checkout?"
- Accept "done", "that's all", "checkout", "I'm ready", "order now" etc. as checkout signals.
- Use the customer's name (from profile) whenever it feels natural.
- Keep replies concise — this is WhatsApp, not an email.

### 3. Checkout Flow
When the customer signals they want to checkout:

**Step 1 — Notes:** If `session_notes` is empty, ask: "Any special instructions? (e.g. extra spicy, no onions — or just reply 'none')"

**Step 2 — Delivery Address:**
- If profile has a saved address AND `session_address` is empty, ask: "Should I deliver to *[saved address]*, or somewhere different?"
- If no saved address and `session_address` is empty, ask: "What's your delivery address?"
- If `session_address` is already set, skip this.

**Step 3 — Payment Method:** If `session_payment_method` is empty, ask: "How would you like to pay? Reply *Bank Transfer* or *Pay on Delivery* 💳"

**Step 4 — Confirmation Summary:** Once notes, address, and payment are collected, show a full summary:
```
📋 *Order Summary*

[Item list with quantities and prices]

📍 Delivery: [address]
📝 Notes: [notes or "None"]
💳 Payment: [method]
💰 Total: ₦[amount]

Reply *Yes* to confirm, or tell me what to change.
```

### 4. Confirming the Order
- Set `intent=CONFIRM_ORDER` with `is_confirmed=true` ONLY when the customer clearly says yes (e.g. "yes", "confirm", "looks good", "go ahead", "perfect").
- If they say "no", "wait", "change", or want to modify: set `is_confirmed=false` and help them adjust.

### 5. Payments
- Never generate payment links or account numbers yourself.
- After confirmation, the backend handles payment — just let the customer know it's being processed.

### 6. Tone & Style
- Warm, helpful, emoji-friendly but not overdone.
- Short paragraphs, WhatsApp-friendly formatting (use *bold* for emphasis).
- Don't repeat the full menu unless asked.

---

## OUTPUT FORMAT

Respond with a valid JSON object — no markdown fences, no extra text before or after:

{{
  "intent": "ADD_ITEM" | "REMOVE_ITEM" | "VIEW_MENU" | "VIEW_CART" | "PROCEED_TO_CHECKOUT" | "PROVIDE_NOTES" | "PROVIDE_ADDRESS" | "SELECT_PAYMENT_METHOD" | "CONFIRM_ORDER" | "CANCEL" | "GENERAL_CHAT",
  "items": [
    {{
      "matched_menu_id": <int or null>,
      "item_name": "<exact or best-match name from the menu>",
      "quantity": <int>
    }}
  ],
  "extracted_notes": "<special instructions string, or null if not provided this turn>",
  "extracted_address": "<delivery address string, or null if not provided this turn>",
  "extracted_payment_method": "TRANSFER" | "PAY_ON_DELIVERY" | null,
  "is_confirmed": true | false | null,
  "reply_message": "<The actual friendly WhatsApp message to send the customer>"
}}

Rules:
- `items` is `[]` unless intent is ADD_ITEM or REMOVE_ITEM.
- `extracted_notes` is null unless the customer explicitly provided notes THIS turn.
- `extracted_address` is null unless they provided or confirmed an address THIS turn.
- `extracted_payment_method` is null unless they specified payment THIS turn.
- `is_confirmed` is null unless intent is CONFIRM_ORDER.
- `reply_message` is ALWAYS populated — it is the only thing the customer sees.
- Output ONLY the JSON object. No preamble, no trailing text.
"""


def _build_cart_json(cart: dict, menu_items_map: dict) -> list:
    """Convert the raw {item_id: qty} cart into a readable list for the AI."""
    result = []
    for item_id_str, qty in cart.items():
        item = menu_items_map.get(int(item_id_str))
        if item:
            result.append({
                'id': item.id,
                'name': item.name,
                'quantity': qty,
                'unit_price': float(item.price),
                'subtotal': float(item.price * qty),
            })
    return result


def ai_process_message(menu_items, profile, session, user_message: str) -> dict:
    """
    Send the customer's message to Claude with full ordering context.
    Returns the parsed JSON intent object.
    """
    # Build readable menu list for the prompt
    menu_json = json.dumps([
        {
            'id': item.id,
            'position': i + 1,
            'name': item.name,
            'description': item.description,
            'price': float(item.price),
            'available': item.is_available,
        }
        for i, item in enumerate(menu_items)
    ], ensure_ascii=False)

    menu_map = {item.id: item for item in menu_items}

    customer_profile_json = json.dumps({
        'name': profile.full_name or None,
        'saved_delivery_address': profile.delivery_address or None,
    }, ensure_ascii=False)

    cart_json = json.dumps(_build_cart_json(session.cart, menu_map), ensure_ascii=False)

    prompt = SYSTEM_PROMPT.format(
        menu_json=menu_json,
        customer_profile_json=customer_profile_json,
        session_state=session.state,
        cart_json=cart_json if session.cart else '[]',
        session_notes=session.notes or '',
        session_address=session.extracted_address or '',
        session_payment_method=session.payment_method or '',
        user_message=user_message,
    )

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name='gemini-2.0-flash',
        system_instruction=prompt,
        generation_config=genai.GenerationConfig(
            temperature=0.4,          # slightly creative but consistent
            max_output_tokens=1024,
        ),
    )

    response = model.generate_content(user_message)
    raw = response.text.strip()

    # Strip accidental markdown fences if the model wraps its output
    if raw.startswith('```'):
        raw = raw.split('```')[1]
        if raw.startswith('json'):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)


# ---------------------------------------------------------------------------
# Formatting helpers (kept for any direct use)
# ---------------------------------------------------------------------------

def format_menu(menu_items) -> str:
    lines = ["Here's our menu:\n"]
    for i, item in enumerate(menu_items, 1):
        lines.append(f"{i}. {item.name} — ₦{item.price:,.0f}")
    lines.append("\nReply with a number or item name to add to your cart.")
    return "\n".join(lines)


def format_cart(cart: dict, menu_items_map: dict) -> str:
    if not cart:
        return "Your cart is empty."
    lines = ["🛒 *Your cart:*\n"]
    total = 0
    for item_id, quantity in cart.items():
        item = menu_items_map.get(int(item_id))
        if item:
            subtotal = item.price * quantity
            total += subtotal
            lines.append(f"- {quantity}× {item.name} — ₦{subtotal:,.0f}")
    lines.append(f"\n*Total: ₦{total:,.0f}*")
    lines.append("\nAdd more items, or reply *done* to checkout.")
    return "\n".join(lines)
