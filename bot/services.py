import logging
from django.conf import settings
from twilio.rest import Client

logger = logging.getLogger(__name__)


def get_twilio_client():
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_whatsapp_message(to: str, body: str):
    try:
        client = get_twilio_client()
        message = client.messages.create(
            from_=settings.TWILIO_WHATSAPP_NUMBER,
            to=f'whatsapp:{to}' if not to.startswith('whatsapp:') else to,
            body=body,
        )
        logger.info("WhatsApp message sent to %s: %s", to, message.sid)
        return message
    except Exception as exc:
        logger.error("Failed to send WhatsApp message to %s: %s", to, exc)
        raise


def notify_payment_confirmed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"✅ Payment confirmed for Order #{order.id}! Your order is now being prepared."
    )


def notify_order_completed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"🎉 Your Order #{order.id} is complete! We hope you enjoy your meal."
    )