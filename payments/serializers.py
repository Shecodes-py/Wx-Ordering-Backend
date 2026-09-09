from rest_framework import serializers

from dashboard.models import Order


class PaymentSerializer(serializers.ModelSerializer):
    """Payment-shaped view of an Order — for the vendor dashboard's Payment tab.

    Lighter than dashboard.OrderSerializer (no nested items) since this is
    about transaction state, not order contents.
    """
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'customer_name', 'customer_phone', 'total_price',
            'payment_method', 'payment_status', 'squad_transaction_ref',
            'status', 'paid_at', 'created_at',
        ]
        read_only_fields = fields
