from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
import json

from twilio.twiml.messaging_response import MessagingResponse
from .models import BotSession
from profiles.models import Profile 

# Create your views here.
@csrf_exempt
def whatsapp_webhook(request):
    if request.method != 'POST':
        return HttpResponse("Method not allowed", status=405)

    # 1. Parse incoming data from Twilio (sent as Form Data, not JSON)
    incoming_msg = request.POST.get('Body', '').strip()
    from_number = request.POST.get('From', '')  # Looks like 'whatsapp:+1234567890'
    
    # Strip the 'whatsapp:' prefix to match your database format if needed
    clean_phone = from_number.replace('whatsapp:', '')

    # 2. Get or create the user profile and their bot session
    # Adjust this logic depending on how your Profile model handles creation
    profile, created = Profile.objects.get_or_create(
        phone_number=clean_phone,
        defaults={'name': 'WhatsApp User'} 
    )
    session, created = BotSession.objects.get_or_create(profile=profile)

    # 3. Process Bot Logic based on Session State
    reply_text = process_bot_state(session, incoming_msg)

    # 4. Use TwiML to send the synchronous reply back to Twilio
    twilio_response = MessagingResponse()
    twilio_response.message(reply_text)

    return HttpResponse(str(twilio_response), content_type='application/xml')


def process_bot_state(session, incoming_msg):
    """
    State machine logic for your chatbot.
    Updates the session state and cart, then returns a string reply.
    """
    state = session.state.upper()
    message = incoming_msg.lower()

    if state == 'START':
        session.state = 'MENU'
        session.save()
        return "Welcome to our food bot! 🍔\nReply with 'MENU' to see what we have, or 'HELP' for assistance."

    elif state == 'MENU':
        if 'menu' in message:
            return "Today's Specials:\n1. Pizza 🍕\n2. Burger 🍔\nReply with the item number to add it to your cart."
        elif '1' in message:
            # Update the JSON cart
            cart = session.cart
            cart['Pizza'] = cart.get('Pizza', 0) + 1
            session.cart = cart
            session.state = 'CHECKOUT'
            session.save()
            return "Added Pizza to your cart! Reply with 'CHECKOUT' to finalize your order."
        else:
            return "I didn't quite get that. Type 'MENU' to see choices."

    elif state == 'CHECKOUT':
        if 'checkout' in message:
            session.state = 'START' # Reset state after order
            session.cart = {}
            session.save()
            return "Order placed! We are waiting for payment confirmation. 🎉"
        
    # Default fallback
    return "Sorry, something went wrong. Let's start over!"