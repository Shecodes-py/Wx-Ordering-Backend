import datetime
import logging

from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, ExpressionWrapper, DecimalField
from django.db.models.functions import TruncDate
from django.http import StreamingHttpResponse

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema

from .models import MenuItem, Order, OrderItem, Feedback, BusinessSettings
from .serializers import (
    MenuItemSerializer, OrderSerializer, FeedbackSerializer,
    FeedbackResponseSerializer, BusinessSettingsSerializer, AnalyticsSerializer,
)

from bot.models import BotSession

logger = logging.getLogger(__name__)

import time
import json as json_module

class OrderStreamView(APIView):
    # text/event-stream, not JSON — not representable as an OpenAPI response.
    @extend_schema(exclude=True)
    def get(self, request):
        def event_stream():
            last_check = timezone.now()
            while True:
                # updated_at (not created_at) so this also pushes status/payment
                # changes on existing orders (e.g. a Squad webhook confirming
                # payment) — not just brand-new orders.
                new_orders = (
                    Order.objects
                    .filter(updated_at__gt=last_check)
                    .select_related('customer')
                    .prefetch_related('items__menu_item')
                    .order_by('-updated_at')
                )
                for order in new_orders:
                    data = OrderSerializer(order).data
                    yield f"data: {json_module.dumps(data, default=str)}\n\n"
                
                yield ": heartbeat\n\n"
                last_check = timezone.now()
                time.sleep(3)

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response
    
    


class MenuItemViewSet(viewsets.ModelViewSet):
    queryset = MenuItem.objects.all().order_by('-created_at')
    serializer_class = MenuItemSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_available']
    search_fields = ['name', 'description']
    ordering_fields = ['price', 'created_at', 'name']

    @action(detail=True, methods=['post'], url_path='toggle')
    def toggle_availability(self, request, pk=None):
        item = self.get_object()
        item.is_available = not item.is_available
        item.save(update_fields=['is_available'])
        return Response({'id': item.id, 'is_available': item.is_available})


class PublicMenuView(ListAPIView):
    queryset = MenuItem.objects.filter(is_available=True).order_by('id')
    serializer_class = MenuItemSerializer
    permission_classes = [AllowAny]


class OrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Order.objects
        .select_related('customer')
        .prefetch_related('items__menu_item')
        .order_by('-created_at')
    )
    serializer_class = OrderSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'fulfillment_type', 'payment_method', 'payment_status']
    ordering_fields = ['created_at', 'total_price']

    @action(detail=False, methods=['get'])
    def recent(self, request):
        cutoff = timezone.now() - datetime.timedelta(hours=24)
        recent_orders = self.get_queryset().filter(created_at__gte=cutoff)
        serializer = self.get_serializer(recent_orders, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        from meta_bot.services import notify_order_accepted
        order = self.get_object()
        if order.status != Order.Status_Choices.Pending:
            return Response(
                {'detail': f'Cannot accept an order with status "{order.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.Status_Choices.Active
        order.save(update_fields=['status'])
        try:
            notify_order_accepted(order)
        except Exception as exc:
            logger.error("Failed to send acceptance notification for order #%s: %s", order.id, exc)
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        order = self.get_object()
        if order.status != Order.Status_Choices.Pending:
            return Response(
                {'detail': f'Cannot decline an order with status "{order.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.Status_Choices.Declined
        order.save(update_fields=['status'])
        return Response(OrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        from meta_bot.services import notify_order_completed, request_feedback
        order = self.get_object()
        if order.status != Order.Status_Choices.Active:
            return Response(
                {'detail': f'Cannot complete an order with status "{order.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.Status_Choices.Completed
        update_fields = ['status']
        
        if (order.payment_method == Order.Payment_Method_Choices.PAYMENT_METHOD_POD
                and order.payment_status != Order.Payment_Status_Choices.PAYMENT_STATUS_PAID):
            order.payment_status = Order.Payment_Status_Choices.PAYMENT_STATUS_PAID
            order.paid_at = timezone.now()
            update_fields += ['payment_status', 'paid_at']
        order.save(update_fields=update_fields)
        try:
            notify_order_completed(order)
        except Exception as exc:
            logger.error("Failed to send completion notification for order #%s: %s", order.id, exc)
        try:
            session = order.customer.bot_session
            session.pending_feedback_order = order
            session.save(update_fields=['pending_feedback_order'])
            request_feedback(order)
        except Exception as exc:
            logger.error("Failed to request feedback for order #%s: %s", order.id, exc)
        return Response(OrderSerializer(order).data)


class FeedbackViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Feedback.objects
        .select_related('customer', 'order')
        .order_by('-created_at')
    )
    serializer_class = FeedbackSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['order', 'customer']

    @extend_schema(request=FeedbackResponseSerializer, responses=FeedbackSerializer)
    @action(detail=True, methods=['post'])
    def respond(self, request, pk=None):
        from meta_bot.services import send_whatsapp_message
        feedback = self.get_object()
        body = FeedbackResponseSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        message = body.validated_data['message']

        feedback.vendor_response = message
        feedback.vendor_responded_at = timezone.now()
        feedback.save(update_fields=['vendor_response', 'vendor_responded_at'])

        try:
            send_whatsapp_message(
                feedback.customer.phone_number,
                f"💬 A reply from the vendor about your feedback:\n\n{message}",
            )
        except Exception as exc:
            logger.error("Failed to send feedback response WhatsApp message for feedback #%s: %s", feedback.id, exc)

        return Response(FeedbackSerializer(feedback).data)


class AnalyticsView(APIView):
    @extend_schema(responses=AnalyticsSerializer)
    def get(self, request):
        now = timezone.now()
        tz = timezone.get_current_timezone()
        today_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - datetime.timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        year_start = today_start.replace(month=1, day=1)
        thirty_days_ago = today_start - datetime.timedelta(days=29)

        selected = request.query_params.get('period', '').lower()
        if selected not in ('today', 'week', 'month', 'all'):
            selected = 'today'

        paid = Order.objects.filter(
            status=Order.Status_Choices.Completed,
            payment_status=Order.Payment_Status_Choices.PAYMENT_STATUS_PAID,
        )

        def revenue_for(qs):
            return qs.aggregate(t=Sum('total_price'))['t'] or 0

        revenue = {
            'daily': revenue_for(paid.filter(updated_at__gte=today_start)),
            'weekly': revenue_for(paid.filter(updated_at__gte=week_start)),
            'monthly': revenue_for(paid.filter(updated_at__gte=month_start)),
            'annual': revenue_for(paid.filter(updated_at__gte=year_start)),
            'lifetime': revenue_for(paid),
        }

        all_orders = Order.objects
        orders = {
            'pending': all_orders.filter(status=Order.Status_Choices.Pending).count(),
            'active': all_orders.filter(status=Order.Status_Choices.Active).count(),
            'completed': all_orders.filter(status=Order.Status_Choices.Completed).count(),
            'declined': all_orders.filter(status=Order.Status_Choices.Declined).count(),
            'today_total': all_orders.filter(created_at__gte=today_start).count(),
            'today_completed': all_orders.filter(status=Order.Status_Choices.Completed, updated_at__gte=today_start).count(),
        }

        unique_visitors_today = BotSession.objects.filter(updated_at__gte=today_start).count()

        # Headline stats per period — drives the dashboard's
        # Today / This Week / This Month tabs (computed for all periods so the
        # frontend can switch without extra round-trips).
        def period_stats(start, orders_qs=all_orders):
            return {
                'orders_total': orders_qs.filter(created_at__gte=start).count(),
                'orders_completed': orders_qs.filter(status=Order.Status_Choices.Completed, created_at__gte=start).count(),
                'earnings': revenue_for(paid.filter(paid_at__gte=start)),
                'visitors': BotSession.objects.filter(updated_at__gte=start).count(),
            }

        periods = {
            'today': period_stats(today_start),
            'week': period_stats(week_start),
            'month': period_stats(month_start),
            'all': {
                'orders_total': all_orders.count(),
                'orders_completed': all_orders.filter(status=Order.Status_Choices.Completed).count(),
                'earnings': revenue['lifetime'],
                'visitors': BotSession.objects.count(),
            },
        }

        completed_count = orders['completed']
        aov = round(revenue['lifetime'] / completed_count, 2) if completed_count else 0

        revenue_by_payment_method = {
            'TRANSFER': revenue_for(paid.filter(payment_method=Order.Payment_Method_Choices.PAYMENT_METHOD_TRANSFER)),
            'PAY_ON_DELIVERY': revenue_for(paid.filter(payment_method=Order.Payment_Method_Choices.PAYMENT_METHOD_POD)),
        }

        revenue_by_fulfillment = {
            'PICKUP': revenue_for(paid.filter(fulfillment_type=Order.Fulfillment_Type_Choices.FULFILLMENT_PICKUP)),
            'DELIVERY': revenue_for(paid.filter(fulfillment_type=Order.Fulfillment_Type_Choices.FULFILLMENT_DELIVERY)),
        }

        best_sellers = (
            OrderItem.objects
            .filter(order__created_at__gte=thirty_days_ago)
            .annotate(line_total=F('unit_price') * F('quantity'))
            .values('menu_item__name')
            .annotate(
                quantity=Sum('quantity'),
                revenue=Sum('line_total', output_field=DecimalField(max_digits=12, decimal_places=2)),
            )
            .order_by('-quantity')[:5]
        )

        trend_7 = (
            Order.objects
            .filter(created_at__gte=today_start - datetime.timedelta(days=6))
            .annotate(day=TruncDate('created_at', tzinfo=tz))
            .values('day')
            .annotate(count=Count('id'), revenue=Sum('total_price'))
            .order_by('day')
        )

        trend_30 = (
            Order.objects
            .filter(created_at__gte=thirty_days_ago)
            .annotate(day=TruncDate('created_at', tzinfo=tz))
            .values('day')
            .annotate(count=Count('id'), revenue=Sum('total_price'))
            .order_by('day')
        )

        feedback_summary = Feedback.objects.aggregate(
            total=Count('id'),
            average_rating=Avg('rating'),
        )

        rating_breakdown = {
            str(i): Feedback.objects.filter(rating=i).count()
            for i in range(1, 6)
        }

        return Response({
            'selected_period': selected,
            'revenue': revenue,
            'orders': orders,
            'unique_visitors_today': unique_visitors_today,
            'periods': periods,
            'trend_last_7_days': list(trend_7),
            'trend_last_30_days': list(trend_30),
            'aov': aov,
            'revenue_by_payment_method': revenue_by_payment_method,
            'revenue_by_fulfillment': revenue_by_fulfillment,
            'best_sellers': list(best_sellers),
            'feedback': {
                'total': feedback_summary['total'],
                'average_rating': round(feedback_summary['average_rating'] or 0, 1),
                'breakdown': rating_breakdown,
            }
        })


class BusinessSettingsView(APIView):
    """Vendor's own business info (currently just name + address) — a
    singleton, not a list: GET/PUT only, no id in the URL."""

    @extend_schema(responses=BusinessSettingsSerializer)
    def get(self, request):
        return Response(BusinessSettingsSerializer(BusinessSettings.get_solo()).data)

    @extend_schema(request=BusinessSettingsSerializer, responses=BusinessSettingsSerializer)
    def put(self, request):
        settings_obj = BusinessSettings.get_solo()
        serializer = BusinessSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)