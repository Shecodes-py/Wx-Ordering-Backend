import random

from django.db import models
from django.db.models import Sum, F, ExpressionWrapper, DecimalField as DBDecimal
from django.utils import timezone
from profiles.models import Profile

# Create your models here.

# No 0/O/1/I — avoids confusion when an order number is read out over WhatsApp.
_ORDER_CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _generate_order_number(created_at=None):
    """'{MMDD}-{2 random chars}', e.g. '0910-K3' — regenerated with a wider
    suffix on the rare collision so it stays unique without ever leaking a
    running total of how many orders have ever been placed."""
    date_part = (created_at or timezone.now()).strftime('%m%d')
    for _ in range(10):
        suffix = ''.join(random.choices(_ORDER_CODE_CHARS, k=2))
        candidate = f'{date_part}-{suffix}'
        if not Order.objects.filter(order_number=candidate).exists():
            return candidate
    suffix = ''.join(random.choices(_ORDER_CODE_CHARS, k=4))
    return f'{date_part}-{suffix}'


class MenuItem(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image_url = models.URLField(blank=True, null=True)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.price < 0:
            raise ValueError("Price cannot be negative.")
        super().save(*args, **kwargs)


class Order(models.Model):
    class Status_Choices(models.TextChoices):
        Pending = 'PENDING', 'Pending'
        Active = 'ACTIVE', 'Active'
        Completed = 'COMPLETED', 'Completed'
        Declined = 'DECLINED', 'Declined'

    class Payment_Method_Choices(models.TextChoices):
        PAYMENT_METHOD_TRANSFER = 'TRANSFER', 'Bank Transfer'
        PAYMENT_METHOD_POD = 'PAY_ON_DELIVERY', 'Pay on Delivery'

    class Fulfillment_Type_Choices(models.TextChoices):
        FULFILLMENT_PICKUP = 'PICKUP', 'Pickup'
        FULFILLMENT_DELIVERY = 'DELIVERY', 'Delivery'

    class Payment_Status_Choices(models.TextChoices):
        PAYMENT_STATUS_UNPAID = 'UNPAID', 'Unpaid'
        PAYMENT_STATUS_PAID = 'PAID', 'Paid'



    customer = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='orders')
    # Customer/vendor-facing identifier — the DB pk stays internal (used only
    # for API routing) so it never reveals a running order count.
    order_number = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    status = models.CharField(max_length=20, choices=Status_Choices.choices, default=Status_Choices.Pending)
    fulfillment_type = models.CharField(max_length=20, choices=Fulfillment_Type_Choices.choices, default=Fulfillment_Type_Choices.FULFILLMENT_PICKUP)
    payment_method = models.CharField(max_length=20, choices=Payment_Method_Choices.choices, default=Payment_Method_Choices.PAYMENT_METHOD_TRANSFER)
    payment_status = models.CharField(max_length=20, choices=Payment_Status_Choices.choices, default=Payment_Status_Choices.PAYMENT_STATUS_UNPAID)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    squad_transaction_ref = models.CharField(max_length=100, blank=True, null=True, unique=True)
    squad_virtual_account = models.JSONField(blank=True, null=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Order {self.order_number or self.id} — {self.customer.full_name} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = _generate_order_number()
        super().save(*args, **kwargs)

    def recalculate_total(self):
        result = self.items.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('unit_price') * F('quantity'),
                    output_field=DBDecimal(max_digits=10, decimal_places=2),
                )
            )
        )
        self.total_price = result['total'] or 0
        self.save(update_fields=['total_price'])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}× {self.menu_item.name} @ ₦{self.unit_price}"

    @property
    def subtotal(self):
        return self.unit_price * self.quantity


class Feedback(models.Model):
    customer = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='feedback')
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='feedback')
    message = models.TextField()
    rating = models.PositiveIntegerField(default=5)
    vendor_response = models.TextField(blank=True, null=True)
    vendor_responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # review_flag = models.BooleanField(default=False)

    def __str__(self):
        return f"Feedback from {self.customer.full_name} on Order #{self.order_id}"
    
    def rating_value(self, value):
        if not (1 <= value <= 5):
            raise ValueError("Ratings must be between 1 and 5.")
        return value
    
    # def review_flag(self):
    #     if self.rating >= 4:
    #         return False # Positive feedback
    #     elif self.rating <= 2:
    #         return True # Negative feedback
    #     return False # Neutral feedback


class BusinessSettings(models.Model):
    """Singleton — one row holds the vendor's own business info. Use
    get_solo() rather than the manager directly."""
    name = models.CharField(max_length=100, blank=True, default='')
    address = models.TextField(blank=True, default='')

    def __str__(self):
        return self.name or 'Business Settings'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)