import logging

from django.db import transaction as db_transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from dashboard.models import MenuItem, Order, OrderItem
from profiles.models import Profile

from .models import BotSession
from .nlu import process_message
from .services import send_whatsapp_message, format_cart

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        incoming_msg = request.data.get('Body', '').strip()
        from_number = request.data.get('From', '').replace('whatsapp:', '').strip()

        if not from_number or not incoming_msg:
            return HttpResponse(status=400)

        try:
            self._handle(from_number, incoming_msg)
        except Exception:
            logger.exception("Unhandled bot error for %s", from_number)
            try:
                send_whatsapp_message(
                    from_number,
                    "Oops, something went wrong on our end! 😅 Please try again or reply *hi* to restart."
                )
            except Exception:
                pass

        # Always return 200 so Twilio doesn't retry
        return HttpResponse(status=200)

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _handle(self, phone: str, msg: str):
        profile, _ = Profile.objects.get_or_create(
            phone_number=phone,
            defaults={'full_name': '', 'delivery_address': ''},
        )
        session, _ = BotSession.objects.get_or_create(profile=profile)

        # Fetch available menu items once — used by AI and by order creation
        menu_items = list(MenuItem.objects.filter(is_available=True).order_by('id'))

        # Let the AI interpret the message and decide what to do
        try:
            intent_data = process_message(menu_items, profile, session, msg)
        except Exception as exc:
            logger.error("NLU processing failed for %s: %s", phone, exc)
            send_whatsapp_message(
                phone,
                "I had trouble understanding that — could you rephrase? 😊 Reply *hi* to start fresh."
            )
            return

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

        if reply:
            send_whatsapp_message(phone, reply)

    # ------------------------------------------------------------------
    # Order creation
    # ------------------------------------------------------------------

    def _create_order(self, phone: str, session: BotSession, profile: Profile):
        from payments.services import create_squad_virtual_account

        delivery_address = session.extracted_address or profile.delivery_address
        raw_payment = session.payment_method or 'TRANSFER'
        payment_method = (
            Order.Payment_Method_Choices.PAYMENT_METHOD_POD
            if raw_payment == 'PAY_ON_DELIVERY'
            else Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER
        )

        try:
            with db_transaction.atomic():
                order = Order.objects.create(
                    customer=profile,
                    payment_method=payment_method,
                    notes=session.notes or '',
                )

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

                order.recalculate_total()

        except Exception as exc:
            logger.exception("Failed to create order for %s: %s", phone, exc)
            send_whatsapp_message(
                phone,
                "Sorry, we couldn't place your order right now. Please try again in a moment! 🙏"
            )
            return

        # Reset session before sending messages (so a crash in Twilio doesn't leave session dirty)
        session.reset()

        name = profile.full_name or "there"

        if payment_method == Order.Payment_Method_Choices.PAYMENT_METHOD_POD:
            send_whatsapp_message(
                phone,
                f"✅ *Order #{order.id} confirmed, {name}!*\n\n"
                f"💰 Total: ₦{order.total_price:,.0f}\n"
                f"📍 Delivering to: {delivery_address}\n\n"
                f"Pay ₦{order.total_price:,.0f} in cash to our rider on arrival. "
                f"We'll notify you when your order is on the way! 🛵"
            )
        else:
            # Generate Squad virtual account for bank transfer
            try:
                va_data = create_squad_virtual_account(order)
                order.squad_virtual_account = va_data
                order.squad_transaction_ref = (
                    va_data.get('transaction_reference')
                    or va_data.get('transaction_ref')
                )
                order.save(update_fields=['squad_virtual_account', 'squad_transaction_ref'])

                account_number = va_data.get('virtual_account_number', 'N/A')
                bank_name = va_data.get('bank_name', 'your bank')

                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Amount: ₦{order.total_price:,.0f}\n"
                    f"📍 Delivering to: {delivery_address}\n\n"
                    f"*Please transfer to:*\n"
                    f"🏦 Bank: {bank_name}\n"
                    f"💳 Account: *{account_number}*\n"
                    f"Ref: {order.squad_transaction_ref}\n\n"
                    f"We'll start preparing your order once payment is confirmed! 🙏"
                )
            except Exception as exc:
                logger.error("Squad VA creation failed for order #%s: %s", order.id, exc)
                send_whatsapp_message(
                    phone,
                    f"✅ *Order #{order.id} placed, {name}!*\n\n"
                    f"💰 Total: ₦{order.total_price:,.0f}\n"
                    f"📍 Delivering to: {delivery_address}\n\n"
                    f"We're generating your payment details and will send them to you shortly! 💳"
                )
