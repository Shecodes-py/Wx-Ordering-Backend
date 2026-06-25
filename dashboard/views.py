import datetime
import logging

from django.utils import timezone
from django.db.models import Sum, Count
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

from .models import MenuItem, Order, Feedback
from .serializers import MenuItemSerializer, OrderSerializer, FeedbackSerializer

from bot.models import BotSession

logger = logging.getLogger(__name__)

import time
import json as json_module

class OrderStreamView(APIView):
    def get(self, request):
        def event_stream():
            last_check = timezone.now()
            while True:
                new_orders = (
                    Order.objects
                    .filter(created_at__gt=last_check)
                    .select_related('customer')
                    .prefetch_related('items__menu_item')
                    .order_by('-created_at')
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
    filterset_fields = ['status', 'payment_method', 'payment_status']
    ordering_fields = ['created_at', 'total_price']

    @action(detail=False, methods=['get'])
    def recent(self, request):
        cutoff = timezone.now() - datetime.timedelta(hours=24)
        recent_orders = self.get_queryset().filter(created_at__gte=cutoff)
        serializer = self.get_serializer(recent_orders, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        order = self.get_object()
        if order.status != Order.Status_Choices.Pending:
            return Response(
                {'detail': f'Cannot accept an order with status "{order.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.Status_Choices.Active
        order.save(update_fields=['status'])
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
        from bot.services import notify_order_completed
        order = self.get_object()
        if order.status != Order.Status_Choices.Active:
            return Response(
                {'detail': f'Cannot complete an order with status "{order.status}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order.status = Order.Status_Choices.Completed
        order.save(update_fields=['status'])
        try:
            notify_order_completed(order)
        except Exception as exc:
            logger.error("Failed to send completion notification for order #%s: %s", order.id, exc)
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


class AnalyticsView(APIView):
    def get(self, request):
        now = timezone.now()
        tz = timezone.get_current_timezone()
        today_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - datetime.timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        year_start = today_start.replace(month=1, day=1)

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
            'today_total': all_orders.filter(created_at__gte=today_start).count(),
            'today_completed': all_orders.filter(status=Order.Status_Choices.Completed, updated_at__gte=today_start).count(),
        }

        
        unique_visitors_today = BotSession.objects.filter(updated_at__gte=today_start).count()

        seven_days_ago = today_start - datetime.timedelta(days=6)
        trend = (
            Order.objects
            .filter(created_at__gte=seven_days_ago)
            .annotate(day=TruncDate('created_at', tzinfo=tz))
            .values('day')
            .annotate(count=Count('id'), revenue=Sum('total_price'))
            .order_by('day')
        )

        from django.db.models import Avg

        feedback_summary = Feedback.objects.aggregate(
        total=Count('id'),
        average_rating=Avg('rating'),
        )

        rating_breakdown = {
            str(i): Feedback.objects.filter(rating=i).count()
            for i in range(1, 6)
    }

        return Response({
            'revenue': revenue,
            'orders': orders,
            'unique_visitors_today': unique_visitors_today,
            'trend_last_7_days': list(trend),

            'feedback': {
            'total': feedback_summary['total'],
            'average_rating': round(feedback_summary['average_rating'] or 0, 1),
            'breakdown': rating_breakdown,
            }
        })