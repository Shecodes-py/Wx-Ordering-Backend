import uuid
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Squad's old /virtual-account/merchant-initiate endpoint (used by this file
# previously) was removed from their API — their current dynamic-VA product is
# a two-step flow:
#   1. create-dynamic-virtual-account — pulls fresh accounts into a pool
#      (occasional/one-time setup; see seed_squad_va_pool below)
#   2. initiate-dynamic-virtual-account — assigns one pool account to a
#      specific amount/reference for one transaction (called per order)
# Both are a Squad-restricted feature — access must be requested from Squad
# (help@squadco.com) before either call will succeed.
VA_DURATION_SECONDS = 3600  # transfer window per order; Squad's unit is seconds


def _headers() -> dict:
    return {
        'Authorization': f'Bearer {settings.SQUAD_SECRET_KEY}',
        'Content-Type': 'application/json',
    }


def seed_squad_va_pool(count: int = 5) -> list:
    """
    One-time (or occasional) setup: pull `count` fresh accounts into Squad's
    dynamic virtual-account pool for this merchant. Run via the
    `seed_squad_va_pool` management command — not called during checkout.
    """
    created = []
    for _ in range(count):
        response = requests.post(
            f'{settings.SQUAD_BASE_URL}/virtual-account/create-dynamic-virtual-account',
            json={},
            headers=_headers(),
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if not (data.get('success') or data.get('status') == 200):
            raise RuntimeError(f"Squad API returned an error: {data.get('message', data)}")
        created.append(data.get('data', data))
    return created


def create_squad_checkout_link(order) -> dict:
    """
    Create a hosted Squad checkout link for this order (card/bank/USSD, chosen
    by the customer on Squad's page). Unlike dynamic virtual accounts, this is
    not behind Squad's restricted-service gate — works in sandbox and live
    without special approval. Fires the same kind of webhook on completion.
    """
    transaction_ref = f"WX-{order.id}-{uuid.uuid4().hex[:8].upper()}"
    amount_kobo = int(order.total_price * 100)
    email = f"{order.customer.phone_number.lstrip('+')}@wx-ordering-customer.com"

    payload = {
        'email': email,
        'amount': amount_kobo,
        'currency': 'NGN',
        'initiate_type': 'inline',
        'transaction_ref': transaction_ref,
        'customer_name': order.customer.full_name or 'Customer',
        'callback_url': getattr(settings, 'SQUAD_CALLBACK_URL', 'https://squadco.com'),
    }

    response = requests.post(
        f'{settings.SQUAD_BASE_URL}/transaction/initiate',
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if data.get('status') != 200 and str(data.get('message', '')).lower() != 'success':
        raise RuntimeError(f"Squad API returned an error: {data.get('message', data)}")

    result = data.get('data', data)
    return {
        'checkout_url': result.get('checkout_url'),
        'transaction_reference': result.get('transaction_ref') or transaction_ref,
    }


def create_squad_virtual_account(order) -> dict:
    """
    Assign one account from the merchant's dynamic-VA pool to this order for a
    one-time transfer. Requires the pool to already be seeded (seed_squad_va_pool)
    and Squad to have granted dynamic-VA access to this merchant account.
    """
    transaction_ref = f"WX-{order.id}-{uuid.uuid4().hex[:8].upper()}"
    amount_kobo = int(order.total_price * 100)
    # Squad requires an email; customers order over WhatsApp with no email on
    # file, so synthesise a stable placeholder from their phone number.
    email = f"{order.customer.phone_number.lstrip('+')}@wx-ordering-customer.com"

    payload = {
        'amount': amount_kobo,
        'transaction_ref': transaction_ref,
        'duration': VA_DURATION_SECONDS,
        'email': email,
        'pass_charge': False,
    }

    response = requests.post(
        f'{settings.SQUAD_BASE_URL}/virtual-account/initiate-dynamic-virtual-account',
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if not (data.get('success') or data.get('status') == 200):
        raise RuntimeError(f"Squad API returned an error: {data.get('message', data)}")

    va = data.get('data', data)
    # Normalise field names to what bot/views.py and meta_bot/views.py expect,
    # so this endpoint swap doesn't ripple out to the calling code.
    return {
        'virtual_account_number': va.get('account_number'),
        'bank_name': va.get('bank'),
        'transaction_reference': va.get('transaction_reference') or transaction_ref,
        'expected_amount': va.get('expected_amount'),
        'expires_at': va.get('expires_at'),
        'raw': va,
    }