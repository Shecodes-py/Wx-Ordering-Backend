"""
Meta WhatsApp Cloud API — send messages via the Graph API.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = 'v21.0'


def _messages_url() -> str:
    phone_id = settings.META_WHATSAPP_PHONE_NUMBER_ID
    return f'https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_id}/messages'


def _headers() -> dict:
    return {
        'Authorization': f'Bearer {settings.META_WHATSAPP_TOKEN}',
        'Content-Type': 'application/json',
    }


def send_whatsapp_message(to: str, body: str) -> dict:
    """
    Send a plain-text WhatsApp message to `to` (E.164, e.g. +2348021434196).
    Returns the Graph API response dict.
    Raises on HTTP error.
    """
    # Meta expects digits only, no leading '+'
    to_clean = to.lstrip('+')

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to_clean,
        'type': 'text',
        'text': {'preview_url': False, 'body': body},
    }

    try:
        response = requests.post(
            _messages_url(),
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        msg_id = data.get('messages', [{}])[0].get('id', '—')
        logger.info("[META] Message sent → %s | wamid=%s", to, msg_id)
        return data
    except requests.HTTPError as exc:
        logger.error(
            "[META] HTTP error sending to %s: %s — %s",
            to, exc, exc.response.text if exc.response else '',
        )
        raise
    except Exception as exc:
        logger.error("[META] Failed to send message to %s: %s", to, exc)
        raise


# ---------------------------------------------------------------------------
# Notification helpers (same interface as bot.services)
# ---------------------------------------------------------------------------

def notify_payment_confirmed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"✅ Payment confirmed for Order #{order.id}!\n\n"
        f"Your order is now being prepared. We'll let you know when it's on the way! 🛵"
    )


def notify_order_completed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"🎉 Your Order #{order.id} is ready and on its way!\n\n"
        f"Thank you for ordering with us — enjoy your meal! 😋"
    )
