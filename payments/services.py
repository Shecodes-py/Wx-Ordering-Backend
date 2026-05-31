import uuid
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def create_squad_virtual_account(order) -> dict:
    transaction_ref = f"WX-{order.id}-{uuid.uuid4().hex[:8].upper()}"
    amount_kobo = int(order.total_price * 100)

    headers = {
        'Authorization': f'Bearer {settings.SQUAD_SECRET_KEY}',
        'Content-Type': 'application/json',
    }

    payload = {
        'transaction_reference': transaction_ref,
        'amount': amount_kobo,
        'phone_number': order.customer.phone_number.lstrip('+'),
        'name': order.customer.full_name,
    }

    response = requests.post(
        f'{settings.SQUAD_BASE_URL}/virtual-account/merchant-initiate',
        json=payload,
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if data.get('success') or data.get('status') == 200:
        return data.get('data', data)

    raise RuntimeError(f"Squad API returned an error: {data.get('message', data)}")