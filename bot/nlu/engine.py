"""
WX NLU Engine — main entry point.

process_message() is a drop-in replacement for the old ai_process_message().
Returns the same dict schema the views.py dispatcher expects.
"""
import logging

from .patterns import detect_intent, _norm, NOTES_NONE
from .extractor import extract_entities, extract_payment_method
from .responder import (
    reply_menu,
    reply_item_added,
    reply_item_not_found,
    reply_item_removed,
    reply_cart,
    reply_ask_notes,
    reply_ask_address,
    reply_address_confirmed,
    reply_ask_payment,
    reply_payment_selected,
    reply_unknown_payment,
    reply_order_summary,
    reply_cancelled,
    reply_empty_cart_checkout,
    reply_general,
    reply_greeting,
)

logger = logging.getLogger(__name__)


def process_message(menu_items: list, profile, session, user_message: str) -> dict:
    """
    Full NLU pipeline:

        message → intent → entities → reply → structured dict

    Returns:
        {
            intent, items, extracted_notes, extracted_address,
            extracted_payment_method, is_confirmed, reply_message
        }
    """
    msg = user_message.strip()
    m = _norm(msg)
    menu_map = {item.id: item for item in menu_items}

    # ---- Profile guard: collect name first if missing ----
    if not profile.full_name:
        profile.full_name = msg[:100]  # Cap at field max_length
        profile.save(update_fields=['full_name'])
        reply = reply_ask_address(saved_address='') if not profile.delivery_address else \
                reply_ask_address(saved_address=profile.delivery_address)
        return _result('GENERAL_CHAT', reply=f"Nice to meet you, {profile.full_name}! 😊\n\n" + reply_ask_address())

    # ---- Detect intent ----
    intent = detect_intent(msg, session.state, session.cart, session)

    # ---- Extract entities ----
    entities = extract_entities(msg, intent, menu_items, session)

    # ---- Generate reply based on intent + context ----
    reply = _generate_reply(
        intent=intent,
        entities=entities,
        msg=msg,
        m=m,
        menu_items=menu_items,
        menu_map=menu_map,
        profile=profile,
        session=session,
    )

    return _result(
        intent=intent,
        items=entities.get('items', []),
        extracted_notes=entities.get('notes'),
        extracted_address=entities.get('address'),
        extracted_payment_method=entities.get('payment_method'),
        is_confirmed=entities.get('is_confirmed'),
        reply=reply,
    )


# ---------------------------------------------------------------------------
# Reply generator — decides which template to use
# ---------------------------------------------------------------------------

def _generate_reply(intent, entities, msg, m, menu_items, menu_map, profile, session) -> str:

    if intent == 'VIEW_MENU':
        return reply_menu(menu_items, profile)

    if intent == 'CANCEL':
        return reply_cancelled(profile)

    if intent == 'VIEW_CART':
        return reply_cart(session.cart, menu_map)

    if intent == 'ADD_ITEM':
        added = entities.get('items', [])
        if not added:
            # Couldn't match anything — maybe it's a greeting or typo
            if m in ('hi', 'hello', 'hey', 'start'):
                return reply_greeting(profile)
            return reply_item_not_found(msg)
        return reply_item_added(added, session.cart, menu_map)

    if intent == 'REMOVE_ITEM':
        removed = entities.get('items', [])
        if not removed:
            return "I couldn't find that item in your cart. Reply *cart* to see what you have 🛒"
        # Build the updated cart for display (views.py will commit the change)
        updated_cart = dict(session.cart)
        for it in removed:
            key = str(it['matched_menu_id'])
            qty = it['quantity']
            if key in updated_cart:
                updated_cart[key] = max(0, updated_cart[key] - qty)
                if updated_cart[key] == 0:
                    del updated_cart[key]
        return reply_item_removed(removed, updated_cart, menu_map)

    if intent == 'PROCEED_TO_CHECKOUT':
        if not session.cart:
            return reply_empty_cart_checkout()
        # Advance through checkout steps
        return _checkout_reply(session, profile, menu_map)

    if intent == 'PROVIDE_NOTES':
        notes = entities.get('notes', '')
        # After saving notes, ask for address next
        address_reply = reply_ask_address(
            saved_address=profile.delivery_address or ''
        )
        if notes:
            return f"Got it — noted: _{notes}_ ✅\n\n{address_reply}"
        return f"No special instructions — got it! ✅\n\n{address_reply}"

    if intent == 'PROVIDE_ADDRESS':
        address = entities.get('address', '')
        if not address:
            return reply_ask_address(saved_address=profile.delivery_address or '')
        confirmed = reply_address_confirmed(address)
        # Next step: ask payment if not set
        if not session.payment_method:
            return f"{confirmed}\n\n{reply_ask_payment()}"
        # Both set → show summary
        return _summary_reply(session, address, menu_map)

    if intent == 'SELECT_PAYMENT_METHOD':
        method = entities.get('payment_method')
        if not method:
            return reply_unknown_payment()
        confirmed = reply_payment_selected(method)
        # Next step: show full summary
        address = session.extracted_address or profile.delivery_address or ''
        notes = session.notes
        summary = reply_order_summary(session.cart, menu_map, address, notes, method)
        return f"{confirmed}\n\n{summary}"

    if intent == 'CONFIRM_ORDER':
        is_confirmed = entities.get('is_confirmed')
        if is_confirmed:
            return ""  # views.py handles order creation and sends its own message
        # Customer said no — let them modify
        return (
            "No problem! 😊 What would you like to change?\n\n"
            "You can add/remove items, update your address, or change the payment method."
        )

    # GENERAL_CHAT fallback
    return reply_general(profile)


def _checkout_reply(session, profile, menu_map) -> str:
    """Walk through checkout steps in order, returning the right prompt."""
    if not session.notes and session.notes != '':
        # notes field is '' default but we use None-check via bool — treat '' as "not yet asked"
        # We distinguish "not asked yet" (notes == '', state != CONFIRMATION) from "asked, answered none"
        # The state transition to CONFIRMATION happens in views.py after this reply is sent.
        return reply_ask_notes()

    if not session.extracted_address:
        return reply_ask_address(saved_address=profile.delivery_address or '')

    if not session.payment_method:
        return reply_ask_payment()

    return reply_order_summary(
        session.cart, menu_map,
        session.extracted_address or profile.delivery_address,
        session.notes,
        session.payment_method,
    )


def _summary_reply(session, new_address, menu_map) -> str:
    return reply_order_summary(
        session.cart, menu_map,
        address=new_address,
        notes=session.notes,
        payment_method=session.payment_method,
    )


# ---------------------------------------------------------------------------
# Dict builder
# ---------------------------------------------------------------------------

def _result(intent, reply, items=None, extracted_notes=None,
            extracted_address=None, extracted_payment_method=None,
            is_confirmed=None) -> dict:
    return {
        'intent': intent,
        'items': items or [],
        'extracted_notes': extracted_notes,
        'extracted_address': extracted_address,
        'extracted_payment_method': extracted_payment_method,
        'is_confirmed': is_confirmed,
        'reply_message': reply,
    }
