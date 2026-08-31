"""
Meta WhatsApp Cloud API webhook — verification + message handling.

Two endpoints:
  GET  /api/meta/webhook/  → Meta sends hub.challenge to verify the webhook URL
  POST /api/meta/webhook/  → Meta delivers incoming messages

The dispatch logic mirrors bot/views.py but calls meta_bot.services
instead of bot.services (different transport, same NLU engine).
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.db import transaction as db_transaction
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View

from dashboard.models import MenuItem, Order, OrderItem
from dashboard.feedback import extract_rating, save_feedback
from profiles.models import Profile

from bot.models import BotSession
from bot.nlu import process_message
from bot.nlu.responder import reply_order_summary

from .services import send_whatsapp_message, send_whatsapp_list, send_whatsapp_buttons

logger = logging.getLogger(__name__)

# Static id → synthetic text for button taps (fed through the same NLU pipeline
# as typed messages, so extractor keyword matching resolves them deterministically).
_LEGACY_NAME_VALUES = {'whatsapp user', 'user', ''}


def _clean_platform_name(raw: str) -> str:
    """Sanitise a WhatsApp-supplied display name; '' if unusable."""
    name = (raw or '').strip()
    return '' if name.lower() in _LEGACY_NAME_VALUES else name[:100]


_BUTTON_REPLY_TEXT = {
    'fulfillment_pickup': 'pickup',
    'fulfillment_delivery': 'delivery',
    'pay_transfer': 'bank transfer',
    'pay_pod': 'pay on delivery',
    'confirm_yes': 'yes',
    'confirm_no': 'no',
}


# ---------------------------------------------------------------------------
# Webhook view
# ---------------------------------------------------------------------------

@method_decorator(csrf_exempt, name='dispatch')
class MetaWebhookView(View):

    # ── GET — webhook verification ────────────────────────────────────────────
    def get(self, request):
        mode        = request.GET.get('hub.mode')
        challenge   = request.GET.get('hub.challenge')
        verify_token = request.GET.get('hub.verify_token')

        logger.info("[META:VERIFY] mode=%s token=%s", mode, verify_token)

        if mode == 'subscribe' and verify_token == settings.META_WEBHOOK_VERIFY_TOKEN:
            logger.info("[META:VERIFY] ✅ Webhook verified")
            return HttpResponse(challenge, content_type='text/plain')

        logger.warning("[META:VERIFY] ❌ Token mismatch — rejecting")
        return HttpResponse(status=403)

    # ── POST — incoming messages ──────────────────────────────────────────────
    def post(self, request):
        raw_body = request.body

        # Validate signature if APP_SECRET is configured
        if settings.META_APP_SECRET:
            if not self._verify_signature(request, raw_body):
                logger.warning("[META:WEBHOOK] Invalid signature — rejecting")
                return HttpResponse(status=403)

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            logger.warning("[META:WEBHOOK] Non-JSON body")
            return HttpResponse(status=400)

        logger.debug("[META:WEBHOOK] Payload: %s", json.dumps(payload)[:400])

        # Extract messages from the nested Meta payload structure
        for entry in payload.get('entry', []):
            for change in entry.get('changes', []):
                value = change.get('value', {})
                if change.get('field') != 'messages':
                    continue
                for message in value.get('messages', []):
                    self._handle_message(message, value)

        # Meta requires a 200 OK immediately — always
        return HttpResponse(status=200)

    # ── Signature verification ────────────────────────────────────────────────
    def _verify_signature(self, request, raw_body: bytes) -> bool:
        sig_header = request.META.get('HTTP_X_HUB_SIGNATURE_256', '')
        if not sig_header.startswith('sha256='):
            return False
        provided = sig_header[len('sha256='):]
        expected = hmac.new(
            settings.META_APP_SECRET.encode(),
            raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, provided)

    # ── Per-message handler ───────────────────────────────────────────────────
    def _handle_message(self, message: dict, value: dict):
        # Meta sends phone numbers without '+'; normalise to E.164
        raw_from = message.get('from', '')
        phone = f'+{raw_from}' if not raw_from.startswith('+') else raw_from
        if not phone:
            logger.warning("[META] Missing phone — skipping")
            return

        # Meta includes the sender's WhatsApp display name alongside the message
        # (not per-message — one contacts[] array for the whole payload) — grab
        # it so we never have to ask new customers for their name.
        wa_name = ''
        for contact in value.get('contacts', []):
            if contact.get('wa_id') == raw_from:
                wa_name = _clean_platform_name((contact.get('profile') or {}).get('name', ''))
                break

        msg_type = message.get('type')
        item_id = None

        if msg_type == 'text':
            body = message.get('text', {}).get('body', '').strip()

        elif msg_type == 'interactive':
            interactive = message.get('interactive', {})
            itype = interactive.get('type')
            if itype == 'list_reply':
                reply_id = interactive.get('list_reply', {}).get('id', '')
                if reply_id.startswith('item_'):
                    try:
                        item_id = int(reply_id.split('_', 1)[1])
                    except ValueError:
                        item_id = None
                body = interactive.get('list_reply', {}).get('title', '')
            elif itype == 'button_reply':
                reply_id = interactive.get('button_reply', {}).get('id', '')
                body = _BUTTON_REPLY_TEXT.get(reply_id, '')
            else:
                logger.info("[META] Skipping unsupported interactive type: %s", itype)
                return

        else:
            logger.info("[META] Skipping non-text/interactive message type: %s", msg_type)
            return

        if not body and item_id is None:
            logger.warning("[META] Missing body/item — skipping")
            return

        logger.info("[META:MSG] from=%s | type=%s | body=%r | item_id=%s", phone, msg_type, body, item_id)

        try:
            self._process(phone, body, item_id=item_id, wa_name=wa_name)
        except Exception:
            logger.exception("[META] Unhandled error for %s", phone)
            try:
                send_whatsapp_message(
                    phone,
                    "Oops, something went wrong on our end! 😅 Reply *hi* to restart."
                )
            except Exception:
                logger.exception("[META] Failed to send error recovery message to %s", phone)

    def _process(self, phone: str, msg: str, item_id: int = None, wa_name: str = ''):
        profile, created = Profile.objects.get_or_create(
            phone_number=phone,
            defaults={'full_name': wa_name, 'delivery_address': ''},
        )
        if created:
            logger.info("[META] New profile for %s | name=%r", phone, wa_name)

        # Sanitise legacy placeholder values; backfill from the WhatsApp display
        # name if we have one and the stored name is missing/legacy.
        dirty_profile = False
        if profile.full_name in ('WhatsApp User', 'User', ''):
            profile.full_name = wa_name
            dirty_profile = True
        if (profile.delivery_address or '').lower() in ('not provided yet', 'not provided', 'n/a'):
            profile.delivery_address = ''
            dirty_profile = True
        if dirty_profile:
            profile.save(update_fields=['full_name', 'delivery_address'])

        session, _ = BotSession.objects.get_or_create(profile=profile)

        # Feedback capture — only when idle (not mid-order) and only if the
        # message actually looks like a rating; otherwise clear the pending
        # flag and let the message flow through normally (never trap a
        # customer who's just saying "hi" to start a new order).
        if item_id is None and session.pending_feedback_order_id and session.state in ('START', ''):
            order = session.pending_feedback_order
            rating = extract_rating(msg)
            if rating is not None:
                save_feedback(order, rating, msg)
                session.pending_feedback_order = None
                session.save(update_fields=['pending_feedback_order'])
                send_whatsapp_message(phone, "Thank you for your feedback! 🙏 We really appreciate it 😊")
                return
            session.pending_feedback_order = None
            session.save(update_fields=['pending_feedback_order'])

        logger.info(
            "[META:SESSION] state=%s | cart=%s | notes=%r | address=%r | payment=%r",
            session.state, session.cart,
            session.notes, session.extracted_address, session.payment_method,
        )

        menu_items = list(MenuItem.objects.filter(is_available=True).order_by('id'))
        logger.info("[META] %d menu items available", len(menu_items))

        # Menu-list taps carry the item's real DB id — resolve to its exact name
        # so NLU matching is exact, regardless of any truncation applied to the
        # row title we sent (list row titles are capped at 24 chars by Meta).
        if item_id is not None:
            item = next((i for i in menu_items if i.id == item_id), None)
            if not item:
                send_whatsapp_message(
                    phone, "Sorry, that item's no longer available 😔 Reply *menu* to see what's available."
                )
                return
            msg = item.name

        try:
            intent_data = process_message(menu_items, profile, session, msg)
        except Exception:
            logger.exception("[META:NLU] Failed for %s", phone)
            send_whatsapp_message(phone, "I had trouble with that — reply *hi* to start fresh 😊")
            return

        logger.info(
            "[META:NLU] intent=%s | items=%s | confirmed=%s",
            intent_data.get('intent'),
            intent_data.get('items'),
            intent_data.get('is_confirmed'),
        )
        logger.info("[META:NLU] reply=%r", (intent_data.get('reply_message') or '')[:120])

        self._dispatch(intent_data, phone, session, profile, menu_items)

    # ── Intent dispatcher (mirrors bot/views.py) ──────────────────────────────
    def _dispatch(self, intent_data: dict, phone: str, session: BotSession,
                  profile: Profile, menu_items: list):
        intent = intent_data.get('intent', 'GENERAL_CHAT')
        reply  = intent_data.get('reply_message', '')
        dirty  = False

        menu_map = {item.id: item for item in menu_items}

        if intent_data.get('extracted_notes') is not None:
            session.notes = intent_data['extracted_notes']
            dirty = True

        if intent_data.get('extracted_fulfillment_type') is not None:
            session.fulfillment_type = intent_data['extracted_fulfillment_type']
            dirty = True

        if intent_data.get('extracted_address') is not None:
            session.extracted_address = intent_data['extracted_address']
            profile.delivery_address  = intent_data['extracted_address']
            profile.save(update_fields=['delivery_address'])
            dirty = True

        if intent_data.get('extracted_payment_method') is not None:
            session.payment_method = intent_data['extracted_payment_method']
            dirty = True

        if intent == 'ADD_ITEM':
            for it in intent_data.get('items', []):
                iid = it.get('matched_menu_id')
                qty = max(1, int(it.get('quantity', 1)))
                if iid and iid in menu_map:
                    cart = session.cart
                    cart[str(iid)] = cart.get(str(iid), 0) + qty
                    session.cart = cart
                    dirty = True
            if session.state in ('START', ''):
                session.state = 'ORDERING'
                dirty = True

        elif intent == 'REMOVE_ITEM':
            for it in intent_data.get('items', []):
                iid = str(it.get('matched_menu_id', ''))
                qty = max(1, int(it.get('quantity', 1)))
                cart = session.cart
                if iid in cart:
                    cart[iid] = max(0, cart[iid] - qty)
                    if cart[iid] == 0:
                        del cart[iid]
                    session.cart = cart
                    dirty = True

        elif intent == 'VIEW_MENU':
            if session.state == 'START':
                session.state = 'ORDERING'
                dirty = True

        elif intent in ('PROCEED_TO_CHECKOUT', 'PROVIDE_NOTES', 'SELECT_FULFILLMENT_TYPE',
                        'PROVIDE_ADDRESS', 'SELECT_PAYMENT_METHOD'):
            session.state = 'CONFIRMATION'
            dirty = True

        elif intent == 'CONFIRM_ORDER':
            if intent_data.get('is_confirmed'):
                if not session.cart:
                    send_whatsapp_message(phone, "Your cart is empty — reply *hi* to start a new order! 😊")
                    return
                self._create_order(phone, session, profile)
                return
            else:
                session.state = 'ORDERING'
                dirty = True

        elif intent == 'CANCEL':
            session.reset()
            send_whatsapp_message(phone, reply or "Order cancelled — reply *hi* whenever you're ready! 👋")
            return

        if dirty:
            session.save()
            logger.info("[META:SESSION] Saved — state=%s | cart=%s", session.state, session.cart)

        self._send_reply(phone, intent, reply, session, menu_map)

    # ── Reply rendering — plain text vs. interactive list/buttons ─────────────
    def _send_reply(self, phone: str, intent: str, reply: str, session: BotSession, menu_map: dict):
        if intent == 'VIEW_MENU':
            self._send_menu(phone, session.profile, list(menu_map.values()))
            return

        if session.state == 'CONFIRMATION':
            notes_set = session.notes is not None
            fulfillment_set = bool(session.fulfillment_type)
            needs_address = session.fulfillment_type == 'DELIVERY'
            address_ready = (not needs_address) or bool(session.extracted_address)
            payment_set = bool(session.payment_method)

            if notes_set and not fulfillment_set:
                self._send_fulfillment_options(phone)
                return

            if notes_set and fulfillment_set and address_ready and not payment_set:
                self._send_payment_options(phone, session)
                return

            if notes_set and fulfillment_set and address_ready and payment_set:
                self._send_confirm(phone, session, menu_map)
                return

        if reply:
            send_whatsapp_message(phone, reply)

    def _send_menu(self, phone: str, profile: Profile, menu_items: list):
        if not menu_items:
            send_whatsapp_message(phone, "Sorry, nothing's on the menu right now 😔")
            return

        rows = [
            {
                'id': f'item_{item.id}',
                'title': item.name,
                'description': f"₦{item.price:,.0f}" + (f" — {item.description}" if item.description else ''),
            }
            for item in menu_items
        ]
        name = profile.full_name
        body = (
            f"Hey {name}! 👋 Tap below to see today's menu 🍽️"
            if name else
            "Hey there! 👋 Tap below to see today's menu 🍽️"
        )
        send_whatsapp_list(
            phone, body=body, button_text="View Menu", rows=rows,
            section_title="Today's Menu", footer="WX Ordering",
        )

    def _send_fulfillment_options(self, phone: str):
        send_whatsapp_buttons(phone, body="Pickup or delivery — which works for you? 🍽️", buttons=[
            {'id': 'fulfillment_pickup', 'title': '🏃 Pickup'},
            {'id': 'fulfillment_delivery', 'title': '🛵 Delivery'},
        ])

    def _send_payment_options(self, phone: str, session: BotSession):
        if session.fulfillment_type == 'DELIVERY':
            address = session.extracted_address or ''
            body = (
                f"📍 Delivering to: {address}\n\nHow would you like to pay? 💳"
                if address else
                "How would you like to pay? 💳"
            )
        else:
            body = "🏃 Pickup confirmed!\n\nHow would you like to pay? 💳"
        send_whatsapp_buttons(phone, body=body, buttons=[
            {'id': 'pay_transfer', 'title': '🏦 Bank Transfer'},
            {'id': 'pay_pod', 'title': '💵 Pay on Delivery'},
        ])

    def _send_confirm(self, phone: str, session: BotSession, menu_map: dict):
        body = reply_order_summary(
            session.cart, menu_map,
            session.extracted_address or '',
            session.notes or '',
            session.payment_method,
            fulfillment_type=session.fulfillment_type,
        )
        send_whatsapp_buttons(phone, body=body, buttons=[
            {'id': 'confirm_yes', 'title': '✅ Confirm Order'},
            {'id': 'confirm_no', 'title': '✏️ Change Something'},
        ])

    # ── Order creation ────────────────────────────────────────────────────────
    def _create_order(self, phone: str, session: BotSession, profile: Profile):
        from payments.services import create_squad_checkout_link

        delivery_address = session.extracted_address or profile.delivery_address
        raw_payment = session.payment_method or 'TRANSFER'
        payment_method = (
            Order.Payment_Method_Choices.PAYMENT_METHOD_POD
            if raw_payment == 'PAY_ON_DELIVERY'
            else Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER
        )
        fulfillment_type = (
            Order.Fulfillment_Type_Choices.FULFILLMENT_DELIVERY
            if session.fulfillment_type == 'DELIVERY'
            else Order.Fulfillment_Type_Choices.FULFILLMENT_PICKUP
        )
        is_pickup = fulfillment_type == Order.Fulfillment_Type_Choices.FULFILLMENT_PICKUP

        logger.info(
            "[META:ORDER] Creating — phone=%s | payment=%s | fulfillment=%s | cart=%s",
            phone, raw_payment, fulfillment_type, session.cart,
        )

        try:
            with db_transaction.atomic():
                order = Order.objects.create(
                    customer=profile,
                    payment_method=payment_method,
                    fulfillment_type=fulfillment_type,
                    notes=session.notes or '',
                )
                items_qs  = MenuItem.objects.filter(id__in=[int(k) for k in session.cart])
                items_map = {item.id: item for item in items_qs}

                for item_id_str, quantity in session.cart.items():
                    item = items_map.get(int(item_id_str))
                    if item:
                        OrderItem.objects.create(
                            order=order,
                            menu_item=item,
                            quantity=quantity,
                            unit_price=item.price,
                        )
                order.recalculate_total()
                logger.info("[META:ORDER] #%s created — total ₦%s", order.id, order.total_price)

        except Exception:
            logger.exception("[META:ORDER] Failed for %s", phone)
            send_whatsapp_message(phone, "Sorry, couldn't place your order right now. Please try again! 🙏")
            return

        session.reset()
        name = profile.full_name or 'there'

        fulfillment_line = (
            "🏃 Pickup — you'll collect this at our location\n\n"
            if is_pickup else
            f"📍 Delivering to: {delivery_address}\n\n"
        )

        if payment_method == Order.Payment_Method_Choices.PAYMENT_METHOD_POD:
            send_whatsapp_message(
                phone,
                f"✅ *Order #{order.id} confirmed, {name}!*\n\n"
                f"💰 Total: ₦{order.total_price:,.0f}\n"
                f"{fulfillment_line}"
                f"Pay cash {'on pickup' if is_pickup else 'to our rider on arrival'}. "
                f"We'll notify you when it's ready! 🛵"
            )
        else:
            try:
                checkout = create_squad_checkout_link(order)
                order.squad_transaction_ref = checkout.get('transaction_reference')
                order.save(update_fields=['squad_transaction_ref'])

                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Amount: ₦{order.total_price:,.0f}\n"
                    f"{fulfillment_line}"
                    f"*Tap to pay:*\n{checkout.get('checkout_url')}\n\n"
                    f"We'll start preparing once payment is confirmed! 🙏"
                )
            except Exception:
                logger.exception("[META:ORDER] Squad checkout link failed for order #%s", order.id)
                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Total: ₦{order.total_price:,.0f}\n\n"
                    f"Payment details coming shortly! 💳"
                )
