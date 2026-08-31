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


def _trunc(text: str, limit: int) -> str:
    text = text or ''
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _send_payload(to: str, payload: dict) -> dict:
    """POST a fully-formed message payload to the Graph API. Raises on HTTP error."""
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


def send_whatsapp_message(to: str, body: str) -> dict:
    """
    Send a plain-text WhatsApp message to `to` (E.164, e.g. +2348021434196).
    Returns the Graph API response dict.
    Raises on HTTP error.
    """
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to.lstrip('+'),
        'type': 'text',
        'text': {'preview_url': False, 'body': body},
    }
    return _send_payload(to, payload)


def send_whatsapp_list(to: str, body: str, button_text: str, rows: list,
                        section_title: str = 'Menu', header: str = None,
                        footer: str = None) -> dict:
    """
    Send a WhatsApp list ("dropdown") message.

    rows: list of {'id', 'title', 'description'} — max 10 total, per Meta's limit.
    Row title max 24 chars, description max 72 chars (truncated here if needed).
    """
    rows = rows[:10]
    interactive = {
        'type': 'list',
        'body': {'text': _trunc(body, 1024)},
        'action': {
            'button': _trunc(button_text, 20),
            'sections': [{
                'title': _trunc(section_title, 24),
                'rows': [
                    {
                        'id': r['id'],
                        'title': _trunc(r['title'], 24),
                        'description': _trunc(r.get('description', ''), 72),
                    }
                    for r in rows
                ],
            }],
        },
    }
    if header:
        interactive['header'] = {'type': 'text', 'text': _trunc(header, 60)}
    if footer:
        interactive['footer'] = {'text': _trunc(footer, 60)}

    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to.lstrip('+'),
        'type': 'interactive',
        'interactive': interactive,
    }
    return _send_payload(to, payload)


def send_whatsapp_buttons(to: str, body: str, buttons: list) -> dict:
    """
    Send a WhatsApp reply-buttons message.

    buttons: list of {'id', 'title'} — max 3, per Meta's limit.
    Button title max 20 chars (truncated here if needed).
    """
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to.lstrip('+'),
        'type': 'interactive',
        'interactive': {
            'type': 'button',
            'body': {'text': _trunc(body, 1024)},
            'action': {
                'buttons': [
                    {'type': 'reply', 'reply': {'id': b['id'], 'title': _trunc(b['title'], 20)}}
                    for b in buttons[:3]
                ],
            },
        },
    }
    return _send_payload(to, payload)


# ---------------------------------------------------------------------------
# Notification helpers (same interface as bot.services)
# ---------------------------------------------------------------------------

def notify_payment_confirmed(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"✅ Payment confirmed for Order #{order.id}!\n\n"
        f"Your order is now being prepared. We'll let you know when it's ready! 🛵"
    )


def notify_order_accepted(order):
    send_whatsapp_message(
        order.customer.phone_number,
        f"✅ Your Order #{order.id} has been accepted!\n\n"
        f"We're getting started on it now — we'll let you know when it's ready! 🍽️"
    )


def notify_order_completed(order):
    if order.fulfillment_type == 'PICKUP':
        body = (
            f"🎉 Your Order #{order.id} has been completed and is ready for pickup!\n\n"
            f"Come grab it whenever you're ready — thanks for ordering with us! 😋"
        )
    else:
        body = (
            f"🎉 Your Order #{order.id} is ready and on its way!\n\n"
            f"Thank you for ordering with us — enjoy your meal! 😋"
        )
    send_whatsapp_message(order.customer.phone_number, body)
