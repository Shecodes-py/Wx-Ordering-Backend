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
from profiles.models import Profile

from bot.models import BotSession
from bot.nlu import process_message

from .services import send_whatsapp_message

logger = logging.getLogger(__name__)


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
        # Only handle text messages
        if message.get('type') != 'text':
            logger.info("[META] Skipping non-text message type: %s", message.get('type'))
            return

        # Meta sends phone numbers without '+'; normalise to E.164
        raw_from = message.get('from', '')
        phone = f'+{raw_from}' if not raw_from.startswith('+') else raw_from
        body = message.get('text', {}).get('body', '').strip()

        if not phone or not body:
            logger.warning("[META] Missing phone or body — skipping")
            return

        logger.info("[META:MSG] from=%s | body=%r", phone, body)

        try:
            self._process(phone, body)
        except Exception:
            logger.exception("[META] Unhandled error for %s", phone)
            try:
                send_whatsapp_message(
                    phone,
                    "Oops, something went wrong on our end! 😅 Reply *hi* to restart."
                )
            except Exception:
                logger.exception("[META] Failed to send error recovery message to %s", phone)

    def _process(self, phone: str, msg: str):
        profile, created = Profile.objects.get_or_create(
            phone_number=phone,
            defaults={'full_name': '', 'delivery_address': ''},
        )
        if created:
            logger.info("[META] New profile for %s", phone)

        # Sanitise legacy placeholder values
        dirty_profile = False
        if profile.full_name in ('WhatsApp User', 'User', ''):
            profile.full_name = ''
            dirty_profile = True
        if (profile.delivery_address or '').lower() in ('not provided yet', 'not provided', 'n/a'):
            profile.delivery_address = ''
            dirty_profile = True
        if dirty_profile:
            profile.save(update_fields=['full_name', 'delivery_address'])

        session, _ = BotSession.objects.get_or_create(profile=profile)

        logger.info(
            "[META:SESSION] state=%s | cart=%s | notes=%r | address=%r | payment=%r",
            session.state, session.cart,
            session.notes, session.extracted_address, session.payment_method,
        )

        menu_items = list(MenuItem.objects.filter(is_available=True).order_by('id'))
        logger.info("[META] %d menu items available", len(menu_items))

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

        elif intent in ('PROCEED_TO_CHECKOUT', 'PROVIDE_NOTES',
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

        if reply:
            send_whatsapp_message(phone, reply)

    # ── Order creation ────────────────────────────────────────────────────────
    def _create_order(self, phone: str, session: BotSession, profile: Profile):
        from payments.services import create_squad_virtual_account

        delivery_address = session.extracted_address or profile.delivery_address
        raw_payment = session.payment_method or 'TRANSFER'
        payment_method = (
            Order.Payment_Method_Choices.PAYMENT_METHOD_POD
            if raw_payment == 'PAY_ON_DELIVERY'
            else Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER
        )

        logger.info(
            "[META:ORDER] Creating — phone=%s | payment=%s | cart=%s",
            phone, raw_payment, session.cart,
        )

        try:
            with db_transaction.atomic():
                order = Order.objects.create(
                    customer=profile,
                    payment_method=payment_method,
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

        if payment_method == Order.Payment_Method_Choices.PAYMENT_METHOD_POD:
            send_whatsapp_message(
                phone,
                f"✅ *Order #{order.id} confirmed, {name}!*\n\n"
                f"💰 Total: ₦{order.total_price:,.0f}\n"
                f"📍 Delivering to: {delivery_address}\n\n"
                f"Pay cash to our rider on arrival. We'll notify you when it's on the way! 🛵"
            )
        else:
            try:
                va_data = create_squad_virtual_account(order)
                order.squad_virtual_account  = va_data
                order.squad_transaction_ref  = (
                    va_data.get('transaction_reference') or va_data.get('transaction_ref')
                )
                order.save(update_fields=['squad_virtual_account', 'squad_transaction_ref'])

                account_number = va_data.get('virtual_account_number', 'N/A')
                bank_name      = va_data.get('bank_name', 'your bank')

                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Amount: ₦{order.total_price:,.0f}\n"
                    f"📍 Delivering to: {delivery_address}\n\n"
                    f"*Transfer to:*\n"
                    f"🏦 Bank: {bank_name}\n"
                    f"💳 Account: *{account_number}*\n"
                    f"Ref: {order.squad_transaction_ref}\n\n"
                    f"We'll start preparing once payment is confirmed! 🙏"
                )
            except Exception:
                logger.exception("[META:ORDER] Squad VA failed for order #%s", order.id)
                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Total: ₦{order.total_price:,.0f}\n\n"
                    f"Payment details coming shortly! 💳"
                )
