import logging

from django.db import transaction as db_transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from dashboard.models import MenuItem, Order, OrderItem
from dashboard.feedback import extract_rating, save_feedback
from profiles.models import Profile

from .models import BotSession
from .nlu import process_message
from .services import send_whatsapp_message

logger = logging.getLogger(__name__)

_LEGACY_NAME_VALUES = {'whatsapp user', 'user', ''}


def _clean_platform_name(raw: str) -> str:
    """Sanitise a Twilio-supplied display name; '' if unusable."""
    name = (raw or '').strip()
    return '' if name.lower() in _LEGACY_NAME_VALUES else name[:100]


@method_decorator(csrf_exempt, name='dispatch')
class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        incoming_msg = request.data.get('Body', '').strip()
        from_number = request.data.get('From', '').replace('whatsapp:', '').strip()
        profile_name = _clean_platform_name(request.data.get('ProfileName', ''))

        logger.info("[WEBHOOK] from=%s | body=%r | name=%r", from_number, incoming_msg, profile_name)

        if not from_number or not incoming_msg:
            logger.warning("[WEBHOOK] Missing From or Body — ignoring")
            return HttpResponse(status=400)

        try:
            self._handle(from_number, incoming_msg, profile_name)
        except Exception:
            logger.exception("[WEBHOOK] Unhandled error for %s", from_number)
            try:
                send_whatsapp_message(
                    from_number,
                    "Oops, something went wrong on our end! 😅 Please try again or reply *hi* to restart."
                )
            except Exception:
                logger.exception("[WEBHOOK] Failed to send fallback message to %s", from_number)

        # Always return 200 so Twilio doesn't retry
        return HttpResponse(status=200)

   
    def _handle(self, phone: str, msg: str, profile_name: str = ''):
        profile, created = Profile.objects.get_or_create(
            phone_number=phone,
            defaults={'full_name': profile_name, 'delivery_address': ''},
        )
        if created:
            logger.info("[PROFILE] New profile created for %s | name=%r", phone, profile_name)

        # Sanitise legacy placeholder values; backfill from Twilio's ProfileName
        # if we have one and the stored name is missing/legacy.
        _dirty_profile = False
        if profile.full_name in ('WhatsApp User', 'User', ''):
            profile.full_name = profile_name
            _dirty_profile = True
        if (profile.delivery_address or '').lower() in ('not provided yet', 'not provided', 'n/a'):
            profile.delivery_address = ''
            _dirty_profile = True
        if _dirty_profile:
            profile.save(update_fields=['full_name', 'delivery_address'])
            logger.info("[PROFILE] Sanitised legacy values for %s", phone)

        session, created = BotSession.objects.get_or_create(profile=profile)
        if created:
            logger.info("[SESSION] New session created for %s", phone)

        # Feedback capture — only when idle (not mid-order) and only if the
        # message actually looks like a rating; otherwise clear the pending
        # flag and let the message flow through normally.
        if session.pending_feedback_order_id and session.state in ('START', ''):
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
            "[SESSION] phone=%s | state=%s | cart=%s | notes=%r | address=%r | payment=%r",
            phone, session.state, session.cart,
            session.notes, session.extracted_address, session.payment_method,
        )

        menu_items = list(MenuItem.objects.filter(is_available=True).order_by('id'))
        logger.info("[MENU] %d items available", len(menu_items))

        try:
            intent_data = process_message(menu_items, profile, session, msg)
        except Exception as exc:
            logger.exception("[NLU] Processing failed for %s: %s", phone, exc)
            send_whatsapp_message(
                phone,
                "I had trouble understanding that — could you rephrase? 😊 Reply *hi* to start fresh."
            )
            return

        logger.info(
            "[NLU] intent=%s | items=%s | notes=%r | address=%r | payment=%r | confirmed=%s",
            intent_data.get('intent'),
            intent_data.get('items'),
            intent_data.get('extracted_notes'),
            intent_data.get('extracted_address'),
            intent_data.get('extracted_payment_method'),
            intent_data.get('is_confirmed'),
        )
        logger.info("[NLU] reply=%r", intent_data.get('reply_message', '')[:120])

        self._dispatch(intent_data, phone, session, profile, menu_items)

    def _dispatch(self, intent_data: dict, phone: str, session: BotSession, profile: Profile, menu_items: list):
        intent = intent_data.get('intent', 'GENERAL_CHAT')
        reply = intent_data.get('reply_message', '')

        # Persist any AI-extracted fields before handling the intent
        dirty = False

        if intent_data.get('extracted_notes') is not None:
            session.notes = intent_data['extracted_notes']
            dirty = True

        if intent_data.get('extracted_address') is not None:
            session.extracted_address = intent_data['extracted_address']
            # Also update the profile's saved address for future orders
            profile.delivery_address = intent_data['extracted_address']
            profile.save(update_fields=['delivery_address'])
            dirty = True

        if intent_data.get('extracted_fulfillment_type') is not None:
            session.fulfillment_type = intent_data['extracted_fulfillment_type']
            dirty = True

        if intent_data.get('extracted_payment_method') is not None:
            session.payment_method = intent_data['extracted_payment_method']
            dirty = True

        menu_map = {item.id: item for item in menu_items}

        # ---- Intent handlers ----

        if intent == 'ADD_ITEM':
            for item_data in intent_data.get('items', []):
                item_id = item_data.get('matched_menu_id')
                qty = max(1, int(item_data.get('quantity', 1)))
                if item_id and item_id in menu_map:
                    cart = session.cart
                    cart[str(item_id)] = cart.get(str(item_id), 0) + qty
                    session.cart = cart
                    dirty = True
            if not session.state or session.state == 'START':
                session.state = 'ORDERING'
                dirty = True

        elif intent == 'REMOVE_ITEM':
            for item_data in intent_data.get('items', []):
                item_id = str(item_data.get('matched_menu_id', ''))
                qty = max(1, int(item_data.get('quantity', 1)))
                cart = session.cart
                if item_id in cart:
                    cart[item_id] = max(0, cart[item_id] - qty)
                    if cart[item_id] == 0:
                        del cart[item_id]
                    session.cart = cart
                    dirty = True

        elif intent == 'VIEW_CART':
            # Reply is handled below — cart view is conversational
            pass

        elif intent == 'VIEW_MENU':
            if session.state == 'START':
                session.state = 'ORDERING'
                dirty = True

        elif intent == 'PROCEED_TO_CHECKOUT':
            session.state = 'CONFIRMATION'
            dirty = True

        elif intent == 'PROVIDE_NOTES':
            session.state = 'CONFIRMATION'
            dirty = True

        elif intent == 'SELECT_FULFILLMENT_TYPE':
            session.state = 'CONFIRMATION'
            dirty = True

        elif intent == 'PROVIDE_ADDRESS':
            session.state = 'CONFIRMATION'
            dirty = True

        elif intent == 'SELECT_PAYMENT_METHOD':
            session.state = 'CONFIRMATION'
            dirty = True

        elif intent == 'CONFIRM_ORDER':
            is_confirmed = intent_data.get('is_confirmed')
            if is_confirmed is True:
                if not session.cart:
                    send_whatsapp_message(phone, "Your cart is empty — reply *hi* to start a new order! 😊")
                    return
                self._create_order(phone, session, profile)
                return  # _create_order sends its own message and resets session
            else:
                # Customer said no / wants to change something
                session.state = 'ORDERING'
                dirty = True

        elif intent == 'CANCEL':
            session.reset()
            # reply is already set by the AI
            send_whatsapp_message(phone, reply or "Order cancelled. Reply *hi* whenever you're ready to order! 👋")
            return

        if dirty:
            session.save()
            logger.info(
                "[SESSION] Saved — state=%s | cart=%s",
                session.state, session.cart,
            )

        if reply:
            logger.info("[TWILIO] Sending reply to %s: %r", phone, reply[:120])
            send_whatsapp_message(phone, reply)

  
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
            "[ORDER] Creating order — phone=%s | payment=%s | fulfillment=%s | cart=%s | address=%r | notes=%r",
            phone, raw_payment, fulfillment_type, session.cart, delivery_address, session.notes,
        )

        try:
            with db_transaction.atomic():
                order = Order.objects.create(
                    customer=profile,
                    payment_method=payment_method,
                    fulfillment_type=fulfillment_type,
                    notes=session.notes or '',
                )
                logger.info("[ORDER] Order #%s created", order.id)

                items_qs = MenuItem.objects.filter(id__in=[int(k) for k in session.cart.keys()])
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
                        logger.debug("[ORDER] Added item: %dx %s @ %s", quantity, item.name, item.price)

                order.recalculate_total()
                logger.info("[ORDER] Total: ₦%s", order.total_price)

        except Exception as exc:
            logger.exception("[ORDER] Failed to create order for %s: %s", phone, exc)
            send_whatsapp_message(
                phone,
                "Sorry, we couldn't place your order right now. Please try again in a moment! 🙏"
            )
            return

        # Reset session before sending messages (so a crash in Twilio doesn't leave session dirty)
        session.reset()

        name = profile.full_name or "there"

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
                f"Pay ₦{order.total_price:,.0f} in cash {'on pickup' if is_pickup else 'to our rider on arrival'}. "
                f"We'll notify you when your order is ready! 🛵"
            )
        else:
            # Generate Squad checkout link for bank transfer / card / USSD
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
                    f"We'll start preparing your order once payment is confirmed! 🙏"
                )
            except Exception as exc:
                logger.exception("[SQUAD] Checkout link creation failed for order #%s: %s", order.id, exc)
                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Total: ₦{order.total_price:,.0f}\n"
                    f"{fulfillment_line}"
                    f"We're generating your payment details and will send them to you shortly! 💳"
                )
