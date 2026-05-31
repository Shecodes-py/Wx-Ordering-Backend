from django.db import models
from django.db.models import Sum, F, ExpressionWrapper, DecimalField as DBDecimal
from profiles.models import Profile

# Create your models here.
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
    STATUS_PENDING = 'PENDING'
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_DECLINED = 'DECLINED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_DECLINED, 'Declined'),
    ]

    PAYMENT_METHOD_TRANSFER = 'TRANSFER'
    PAYMENT_METHOD_POD = 'PAY_ON_DELIVERY'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_TRANSFER, 'Bank Transfer'),
        (PAYMENT_METHOD_POD, 'Pay on Delivery'),
    ]

    PAYMENT_STATUS_UNPAID = 'UNPAID'
    PAYMENT_STATUS_PAID = 'PAID'
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_UNPAID, 'Unpaid'),
        (PAYMENT_STATUS_PAID, 'Paid'),
    ]

    customer = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default=PAYMENT_METHOD_TRANSFER)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_UNPAID)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    squad_transaction_ref = models.CharField(max_length=100, blank=True, null=True, unique=True)
    squad_virtual_account = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order #{self.id} — {self.customer.full_name} ({self.status})"

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
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, related_name='order_items')
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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback from {self.customer.full_name} on Order #{self.order_id}"