from django.shortcuts import render

import json
import hmac
import hashlib
import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction as db_transaction
from django.conf import settings

logger = logging.getLogger(__name__)

# Create your views here.
@csrf_exempt
def squad_webhook(request):
    if request.method != 'POST':
        return HttpResponse(status=405)

    raw_body = request.body
    provided_sig = request.META.get('HTTP_X_SQUAD_ENCRYPTED_BODY', '')

    expected_sig = hmac.new(
        settings.SQUAD_SECRET_KEY.encode('utf-8'),
        raw_body,
        hashlib.sha512,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, provided_sig):
        logger.warning("Squad webhook: invalid signature — rejecting request")
        return HttpResponse(status=403)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    event = payload.get('Event') or payload.get('event', '')

    if event == 'charge_completed':
        _handle_charge_completed(payload.get('Body') or payload.get('body', {}))

    return HttpResponse(status=200)


def _handle_charge_completed(body: dict):
    from dashboard.models import Order
    from bot.services import notify_payment_confirmed

    transaction_ref = (
        body.get('transaction_ref')
        or body.get('transaction_reference')
        or body.get('merchantRef')
    )
    amount_kobo = body.get('amount', 0)
    amount_naira = amount_kobo / 100

    if not transaction_ref:
        logger.error("Squad webhook: no transaction_ref in payload")
        return

    try:
        with db_transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(squad_transaction_ref=transaction_ref)
            except Order.DoesNotExist:
                logger.error("Squad webhook: no order found for ref=%s", transaction_ref)
                return

            if order.payment_status == Order.Payment_Status_Choices.PAYMENT_STATUS_PAID:
                return

            expected = float(order.total_price)
            received = float(amount_naira)
            if abs(expected - received) > 0.01:
                logger.warning("Squad webhook: amount mismatch on order #%s", order.id)
                return

            order.payment_status = Order.Payment_Status_Choices.PAYMENT_STATUS_PAID
            order.status = Order.Status_Choices.Active
            order.save(update_fields=['payment_status', 'status', 'updated_at'])

        notify_payment_confirmed(order)

    except Exception as exc:
        logger.exception("Squad webhook: unexpected error — %s", exc)