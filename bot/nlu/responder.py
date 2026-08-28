"""
Template-based response generator.

All customer-facing text lives here — edit to change tone/branding.
Responses are varied using random.choice() so they don't feel repetitive.
"""
import random
from decimal import Decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick(variants: list) -> str:
    return random.choice(variants)


def _format_price(price) -> str:
    return f"₦{Decimal(price):,.0f}"


def _cart_lines(cart: dict, menu_map: dict) -> list[str]:
    lines = []
    for item_id, qty in cart.items():
        item = menu_map.get(int(item_id))
        if item:
            lines.append(f"  • {qty}× {item.name} — {_format_price(item.price * qty)}")
    return lines


def _cart_total(cart: dict, menu_map: dict) -> Decimal:
    total = Decimal('0')
    for item_id, qty in cart.items():
        item = menu_map.get(int(item_id))
        if item:
            total += item.price * qty
    return total


# ---------------------------------------------------------------------------
# Per-intent response builders
# ---------------------------------------------------------------------------

def reply_menu(menu_items, profile) -> str:
    name = profile.full_name
    greeting = (
        _pick([f"Hey {name}! 👋 Here's what we have today:",
               f"Hi {name}! 😊 Check out our menu:"])
        if name else
        _pick(["Hey there! 👋 Here's what we have today:",
               "Hi! 😊 Here's our menu — what looks good?",
               "Welcome! 🍽️ Here's what's cooking today:"])
    )
    lines = [greeting, ""]
    for i, item in enumerate(menu_items, 1):
        avail = "" if item.is_available else " _(unavailable)_"
        lines.append(f"{i}. *{item.name}*{avail} — {_format_price(item.price)}")
        if item.description:
            lines.append(f"   _{item.description}_")
    lines.append("")
    lines.append(_pick([
        "Reply with a number, item name, or just tell me what you want! 😊",
        "Just type what you'd like — by name or number works! 🙌",
        "What would you like? You can name it or use the number.",
    ]))
    return "\n".join(lines)


def reply_item_added(added_items: list, cart: dict, menu_map: dict) -> str:
    if len(added_items) == 1:
        it = added_items[0]
        item = menu_map.get(it['matched_menu_id'])
        price_line = f" ({_format_price(item.price)} each)" if item else ""
        confirmation = _pick([
            f"Got it! *{it['quantity']}× {it['item_name']}* added{price_line} 🛒",
            f"Added *{it['quantity']}× {it['item_name']}*{price_line} ✅",
            f"Nice choice! *{it['quantity']}× {it['item_name']}* is in your cart{price_line} 👌",
        ])
    else:
        names = ", ".join(f"{i['quantity']}× {i['item_name']}" for i in added_items)
        confirmation = _pick([
            f"Added to your cart: *{names}* 🛒",
            f"Got it! I've added *{names}* ✅",
        ])

    total = _cart_total(cart, menu_map)
    follow_up = _pick([
        f"Cart total: *{_format_price(total)}*. Anything else, or reply *done* to checkout?",
        f"Your total so far: *{_format_price(total)}*. Want to add more, or shall we checkout?",
        f"Running total: *{_format_price(total)}*. Keep adding or reply *done* when ready! 😊",
    ])
    return f"{confirmation}\n\n{follow_up}"


def reply_item_not_found(msg: str) -> str:
    return _pick([
        f"Hmm, I couldn't find *{msg}* on the menu 🤔\nReply *menu* to see what's available, or try a different name.",
        f"I didn't quite catch that — *{msg}* doesn't match anything on our menu.\nReply *menu* to browse what we have! 😊",
    ])


def reply_item_removed(removed_items: list, cart: dict, menu_map: dict) -> str:
    names = ", ".join(f"{i['quantity']}× {i['item_name']}" for i in removed_items)
    total = _cart_total(cart, menu_map)
    return (
        f"Removed *{names}* from your cart ✅\n\n"
        f"Cart total: *{_format_price(total)}*. Anything else?"
    )


def reply_cart(cart: dict, menu_map: dict) -> str:
    if not cart:
        return _pick([
            "Your cart is empty right now 🛒\nReply *menu* to start ordering!",
            "Nothing in your cart yet! Reply *menu* to see what's available 😊",
        ])
    lines = ["🛒 *Your cart:*", ""] + _cart_lines(cart, menu_map)
    total = _cart_total(cart, menu_map)
    lines += ["", f"*Total: {_format_price(total)}*", ""]
    lines.append(_pick([
        "Add more items, or reply *done* to checkout!",
        "Want to add more? Or reply *done* and we'll sort out delivery 😊",
    ]))
    return "\n".join(lines)


def reply_ask_notes() -> str:
    return _pick([
        "Any special instructions for your order? 📝\n(e.g. extra spicy, no onions, well done — or just reply *none*)",
        "Got it! Any cooking or delivery notes? 😊\n(Reply *none* if everything is standard)",
        "Almost there! Any special requests? Like extra sauce or no pepper? 🌶️\n(Or just say *none*)",
    ])


def reply_ask_address(saved_address: str = '') -> str:
    if saved_address:
        return (
            f"Should I deliver to your saved address?\n"
            f"📍 *{saved_address}*\n\n"
            f"Reply *yes* to confirm or send a different address."
        )
    return _pick([
        "What's your delivery address? 📍",
        "Where should we deliver to? Drop your address below 📍",
    ])


def reply_address_confirmed(address: str) -> str:
    return _pick([
        f"Got it! Delivering to: 📍 *{address}*",
        f"Perfect! We'll bring it to: 📍 *{address}*",
    ])


def reply_ask_payment() -> str:
    return (
        "How would you like to pay? 💳\n\n"
        "1️⃣ *Bank Transfer*\n"
        "2️⃣ *Pay on Delivery* (cash to rider)\n\n"
        "Reply *1* or *Bank Transfer*, or *2* or *Pay on Delivery*."
    )


def reply_payment_selected(method: str) -> str:
    label = "Bank Transfer 🏦" if method == 'TRANSFER' else "Pay on Delivery 💵"
    return f"Payment method: *{label}* ✅"


def reply_unknown_payment() -> str:
    return (
        "I didn't quite get that 🤔\n\n"
        "Please reply:\n"
        "• *Bank Transfer* (or *1*)\n"
        "• *Pay on Delivery* (or *2*)"
    )


def reply_order_summary(cart: dict, menu_map: dict, address: str, notes: str, payment_method: str) -> str:
    item_lines = _cart_lines(cart, menu_map)
    total = _cart_total(cart, menu_map)
    payment_label = "Bank Transfer 🏦" if payment_method == 'TRANSFER' else "Pay on Delivery 💵"
    notes_line = notes if notes else "None"

    lines = [
        "📋 *Order Summary*",
        "",
        *item_lines,
        "",
        f"📍 *Delivery:* {address}",
        f"📝 *Notes:* {notes_line}",
        f"💳 *Payment:* {payment_label}",
        f"💰 *Total: {_format_price(total)}*",
        "",
        _pick([
            "Reply *Yes* to confirm, or tell me what to change 😊",
            "All good? Reply *Yes* to place your order, or let me know if anything needs changing.",
        ]),
    ]
    return "\n".join(lines)


def reply_cancelled(profile) -> str:
    name = profile.full_name
    opener = f"No problem, {name}! 👋" if name else "No problem! 👋"
    return f"{opener} Order cancelled. Reply *hi* whenever you're ready to order again 😊"


def reply_empty_cart_checkout() -> str:
    return _pick([
        "Your cart is empty! Reply *menu* to browse and add items first 🛒",
        "Nothing to checkout yet — reply *menu* to see what's available 😊",
    ])


def reply_general(profile) -> str:
    name = profile.full_name
    opener = f"Hey {name}! " if name else "Hey! "
    return (
        f"{opener}I'm here to take your food order 😊\n\n"
        "Reply *menu* to see what's available, or just tell me what you'd like!"
    )


def reply_greeting(profile) -> str:
    name = profile.full_name
    if name:
        return _pick([
            f"Hey {name}! 👋 Great to have you back!\n\nHere's our menu — what would you like today?",
            f"Welcome back, {name}! 😊 Ready to order?",
        ])
    return _pick([
        "Hey there! 👋 Welcome to WX Ordering!\n\nWhat's your name?",
        "Hi! 😊 Welcome — I'm WX, your food ordering assistant!\n\nWhat's your name?",
    ])
