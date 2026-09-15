from django.shortcuts import render

import json
import hmac
import hashlib
import logging
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction as db_transaction
from django.conf import settings

from rest_framework import viewsets, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from dashboard.models import Order
from .serializers import PaymentSerializer

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

    
    if not hmac.compare_digest(expected_sig.lower(), provided_sig.lower()):
        squad_headers = {
            k: v for k, v in request.META.items()
            if k.startswith('HTTP_') and 'SQUAD' in k
        }
        logger.warning(
            "Squad webhook: invalid signature — rejecting request | "
            "provided_len=%d expected_len=%d provided_prefix=%r expected_prefix=%r "
            "squad_headers_seen=%s body_len=%d",
            len(provided_sig), len(expected_sig),
            provided_sig[:12], expected_sig[:12],
            list(squad_headers.keys()), len(raw_body),
        )
        return HttpResponse(status=403)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    event = payload.get('Event') or payload.get('event', '')

    # 'charge_successful' is what Squad's standard checkout (transaction/initiate)
    # fires; 'charge_completed' is kept for the dynamic-VA product in case that's
    # enabled later.
    if event in ('charge_completed', 'charge_successful'):
        _handle_charge_completed(payload.get('Body') or payload.get('body', {}))

    return HttpResponse(status=200)


def _handle_charge_completed(body: dict):
    from meta_bot.services import notify_payment_confirmed

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

            # Payment confirmed — leave status alone (still Pending) so the
            # vendor still has to Accept it in the dashboard, same as a
            # pay-on-delivery order. Accepting is what actually notifies the
            # customer their order was seen; skipping straight to Active here
            # bypassed that step and the vendor's Accept button.
            order.payment_status = Order.Payment_Status_Choices.PAYMENT_STATUS_PAID
            order.paid_at = timezone.now()
            order.save(update_fields=['payment_status', 'paid_at', 'updated_at'])

        notify_payment_confirmed(order)

    except Exception as exc:
        logger.exception("Squad webhook: unexpected error — %s", exc)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """Vendor dashboard's Payment tab — transaction-shaped view of Order."""
    queryset = Order.objects.select_related('customer').order_by('-created_at')
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['payment_method', 'payment_status']
    ordering_fields = ['created_at', 'paid_at', 'total_price']

    @action(detail=False, methods=['get'])
    def summary(self, request):
        return Response(self._compose_summary())

    @staticmethod
    def _compose_summary():
        paid = Order.objects.filter(payment_status=Order.Payment_Status_Choices.PAYMENT_STATUS_PAID)
        pod_outstanding = Order.objects.filter(
            payment_method=Order.Payment_Method_Choices.PAYMENT_METHOD_POD,
            status__in=[Order.Status_Choices.Pending, Order.Status_Choices.Active],
        )
        return {
            'total_collected': paid.aggregate(t=Sum('total_price'))['t'] or 0,
            'transfer_paid_count': paid.filter(payment_method=Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER).count(),
            'pod_outstanding_count': pod_outstanding.count(),
            'pod_outstanding_amount': pod_outstanding.aggregate(t=Sum('total_price'))['t'] or 0,
        }

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        import datetime

        now = timezone.now()
        tz = timezone.get_current_timezone()
        today_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = today_start.replace(day=1)
        year_start = today_start.replace(month=1, day=1)

        paid = Order.objects.filter(payment_status=Order.Payment_Status_Choices.PAYMENT_STATUS_PAID)
        unpaid = Order.objects.filter(payment_status=Order.Payment_Status_Choices.PAYMENT_STATUS_UNPAID)

        def amount_for(qs):
            return qs.aggregate(t=Sum('total_price'))['t'] or 0

        def stats_for(qs):
            return {'count': qs.count(), 'amount': amount_for(qs)}

        transfer = paid.filter(payment_method=Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER)
        pod = paid.filter(payment_method=Order.Payment_Method_Choices.PAYMENT_METHOD_POD)

        payment_method_mix = {
            'TRANSFER': stats_for(transfer),
            'PAY_ON_DELIVERY': stats_for(pod),
        }

        status_distribution = {
            'PAID': stats_for(paid),
            'UNPAID': stats_for(unpaid),
        }

        collected_by_period = {
            'today': amount_for(paid.filter(paid_at__gte=today_start)),
            'month': amount_for(paid.filter(paid_at__gte=month_start)),
            'year': amount_for(paid.filter(paid_at__gte=year_start)),
            'lifetime': amount_for(paid),
        }

        thirty_days_ago = today_start - datetime.timedelta(days=29)
        daily_trend = (
            paid
            .filter(paid_at__gte=thirty_days_ago)
            .annotate(day=TruncDate('paid_at', tzinfo=tz))
            .values('day')
            .annotate(count=Count('id'), amount=Sum('total_price'))
            .order_by('day')
        )

        return Response({
            'summary': self._compose_summary(),
            'payment_method_mix': payment_method_mix,
            'status_distribution': status_distribution,
            'collected_by_period': collected_by_period,
            'daily_trend_last_30_days': list(daily_trend),
        })