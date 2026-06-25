from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny

from twilio.twiml.messaging_response import MessagingResponse
from .models import BotSession
from profiles.models import Profile 
from dashboard.models import MenuItem, Order, OrderItem
from .services import send_whatsapp_message, format_menu, format_cart

import logging
logger = logging.getLogger(__name__)

# Create your views here.
# def process_bot_state(session, incoming_msg):
#     """
#     State machine logic for your chatbot.
#     Updates the session state and cart, then returns a string reply.
#     """
#     state = session.state.upper()
#     message = incoming_msg.lower()

#     if state == 'START':
#         session.state = 'MENU'
#         session.save()
#         return "Welcome to our food bot! 🍔\nReply with 'MENU' to see what we have, or 'HELP' for assistance."

#     elif state == 'MENU':
#         if 'menu' in message:
#             return "Today's Specials:\n1. Pizza 🍕\n2. Burger 🍔\nReply with the item number to add it to your cart."
#         elif '1' in message:
#             # Update the JSON cart
#             cart = session.cart
#             cart['Pizza'] = cart.get('Pizza', 0) + 1
#             session.cart = cart
#             session.state = 'CHECKOUT'
#             session.save()
#             return "Added Pizza to your cart! Reply with 'CHECKOUT' to finalize your order."
#         else:
#             return "I didn't quite get that. Type 'MENU' to see choices."

#     elif state == 'CHECKOUT':
#         if 'checkout' in message:
#             session.state = 'START' # Reset state after order
#             session.cart = {}
#             session.save()
#             return "Order placed! We are waiting for payment confirmation. 🎉"
        
#     # Default fallback
#     return "Sorry, something went wrong. Let's start over!"


# @csrf_exempt
# def whatsapp_webhook(request):
#     if request.method != 'POST':
#         return HttpResponse("Method not allowed", status=405)

#     incoming_msg = request.POST.get('Body', '').strip()
#     from_number = request.POST.get('From', '')
    
#     clean_phone = from_number.replace('whatsapp:', '')

#     profile, created = Profile.objects.get_or_create(
#         phone_number=clean_phone,
#         defaults={
#             'full_name': 'WhatsApp User',
#             'delivery_address': 'Not Provided Yet'
#         }
#     )
#     session, created = BotSession.objects.get_or_create(profile=profile)

#     reply_text = process_bot_state(session, incoming_msg)

#     twilio_response = MessagingResponse()
#     twilio_response.message(reply_text)

#     return HttpResponse(str(twilio_response), content_type='application/xml')



@method_decorator(csrf_exempt, name='dispatch')
class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        incoming_msg = request.data.get('Body', '').strip()
        from_number = request.data.get('From', '').replace('whatsapp:', '')

        if not from_number or not incoming_msg:
            return HttpResponse(status=400)

        try:
            self._handle(from_number, incoming_msg)
        except Exception as exc:
            logger.exception("Bot error for %s: %s", from_number, exc)
            send_whatsapp_message(from_number, "Something went wrong. Please try again.")

        return HttpResponse(status=200)

    def _handle(self, phone, msg):
        msg_lower = msg.lower().strip()

        # get or create profile and session
        profile, _ = Profile.objects.get_or_create(
            phone_number=phone,
            defaults={'full_name': '', 'delivery_address': ''}
        )
        session, _ = BotSession.objects.get_or_create(profile=profile)

        state = session.state

        # allow restart from anywhere
        if msg_lower in ['hi', 'hello', 'start', 'restart', 'menu']:
            if not profile.full_name:
                session.state = 'COLLECTING_NAME'
                session.save()
                send_whatsapp_message(phone, "👋 Welcome to WX Ordering!\n\nWhat's your full name?")
            else:
                self._show_menu(phone, session)
            return

        # state machine
        if state == 'COLLECTING_NAME':
            profile.full_name = msg
            profile.save()
            session.state = 'COLLECTING_ADDRESS'
            session.save()
            send_whatsapp_message(phone, f"Nice to meet you, {msg}! 😊\n\nWhat's your delivery address?")

        elif state == 'COLLECTING_ADDRESS':
            profile.delivery_address = msg
            profile.save()
            self._show_menu(phone, session)

        elif state == 'MENU':
            self._handle_menu_selection(phone, session, profile, msg)

        elif state == 'SELECTING_QUANTITY':
            self._handle_quantity(phone, session, msg)

        elif state == 'CART':
            if msg_lower == 'done':
                self._ask_payment_method(phone, session)
            else:
                self._handle_menu_selection(phone, session, profile, msg)

        elif state == 'SELECTING_PAYMENT':
            self._handle_payment_selection(phone, session, profile, msg)

        else:
            send_whatsapp_message(phone, "Reply with *hi* to start ordering. 😊")

    def _show_menu(self, phone, session):
        items = list(MenuItem.objects.filter(is_available=True).order_by('id'))
        if not items:
            send_whatsapp_message(phone, "Sorry, no items are available right now. Please check back later.")
            return
        session.state = 'MENU'
        session.cart = {}
        session.save()
        send_whatsapp_message(phone, format_menu(items))

    def _handle_menu_selection(self, phone, session, profile, msg):
        items = list(MenuItem.objects.filter(is_available=True).order_by('id'))
        try:
            index = int(msg) - 1
            if index < 0 or index >= len(items):
                raise ValueError
        except ValueError:
            send_whatsapp_message(phone, "Please reply with a valid number from the menu.")
            return

        selected = items[index]
        session.state = 'SELECTING_QUANTITY'
        session.cart['_pending_item_id'] = selected.id
        session.save()
        send_whatsapp_message(phone, f"How many *{selected.name}* would you like?")

    def _handle_quantity(self, phone, session, msg):
        try:
            quantity = int(msg)
            if quantity < 1:
                raise ValueError
        except ValueError:
            send_whatsapp_message(phone, "Please reply with a valid number.")
            return

        item_id = session.cart.pop('_pending_item_id', None)
        if not item_id:
            send_whatsapp_message(phone, "Something went wrong. Reply with *hi* to restart.")
            return

        cart = session.cart
        cart[str(item_id)] = cart.get(str(item_id), 0) + quantity
        session.cart = cart
        session.state = 'CART'
        session.save()

        items = MenuItem.objects.filter(is_available=True)
        items_map = {item.id: item for item in items}
        send_whatsapp_message(phone, format_cart(cart, items_map))

    def _ask_payment_method(self, phone, session):
        session.state = 'SELECTING_PAYMENT'
        session.save()
        send_whatsapp_message(
            phone,
            "How would you like to pay?\n\n1. Bank Transfer\n2. Pay on Delivery"
        )

    def _handle_payment_selection(self, phone, session, profile, msg):
        if msg.strip() == '1':
            payment_method = Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER
        elif msg.strip() == '2':
            payment_method = Order.Payment_Method_Choices.PAYMENT_METHOD_POD
        else:
            send_whatsapp_message(phone, "Please reply with 1 for Bank Transfer or 2 for Pay on Delivery.")
            return

        # create order
        cart = session.cart
        if not cart:
            send_whatsapp_message(phone, "Your cart is empty. Reply with *hi* to start over.")
            return

        order = Order.objects.create(
            customer=profile,
            payment_method=payment_method,
        )

        items = MenuItem.objects.filter(is_available=True)
        items_map = {item.id: item for item in items}

        for item_id, quantity in cart.items():
            item = items_map.get(int(item_id))
            if item:
                OrderItem.objects.create(
                    order=order,
                    menu_item=item,
                    quantity=quantity,
                    unit_price=item.price,
                )

        order.recalculate_total()

        # clear session
        session.state = 'START'
        session.cart = {}
        session.save()

        if payment_method == Order.Payment_Method_Choices.PAYMENT_METHOD_POD:
            send_whatsapp_message(
                phone,
                f"✅ Order #{order.id} confirmed!\n\n"
                f"Total: ₦{order.total_price:,.0f}\n"
                f"Delivering to: {profile.delivery_address}\n\n"
                f"We'll notify you when it's on the way! 🛵"
            )
        else:
            # transfer — Squad virtual account will be added later
            send_whatsapp_message(
                phone,
                f"✅ Order #{order.id} placed!\n\n"
                f"Total: ₦{order.total_price:,.0f}\n\n"
                f"Please wait while we generate your payment details... 💳"
            )