import logging

from django.conf import settings
from twilio.rest import Client

logger = logging.getLogger(__name__)


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



# Re-export so existing imports of ai_process_message keep working.
# views.py now calls process_message directly via bot.nlu, but this alias
# means any other import site won't break.
from .nlu import process_message as ai_process_message  # noqa: F401
