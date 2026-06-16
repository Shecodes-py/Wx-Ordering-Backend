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
    class Status_Choices(models.TextChoices):
        Pending = 'PENDING', 'Pending'
        Active = 'ACTIVE', 'Active'
        Completed = 'COMPLETED', 'Completed'
        Declined = 'DECLINED', 'Declined'

    class Payment_Method_Choices(models.TextChoices):
        PAYMENT_METHOD_TRANSFER = 'TRANSFER', 'Bank Transfer'
        PAYMENT_METHOD_POD = 'PAY_ON_DELIVERY', 'Pay on Delivery'

    class Payment_Status_Choices(models.TextChoices):
        PAYMENT_STATUS_UNPAID = 'UNPAID', 'Unpaid'
        PAYMENT_STATUS_PAID = 'PAID', 'Paid'



    customer = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name='orders')
    status = models.CharField(max_length=20, choices=Status_Choices.choices, default=Status_Choices.Pending)
    payment_method = models.CharField(max_length=20, choices=Payment_Method_Choices.choices, default=Payment_Method_Choices.PAYMENT_METHOD_TRANSFER)
    payment_status = models.CharField(max_length=20, choices=Payment_Status_Choices.choices, default=Payment_Status_Choices.PAYMENT_STATUS_UNPAID)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    squad_transaction_ref = models.CharField(max_length=100, blank=True, null=True, unique=True)
    squad_virtual_account = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

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
    rating = models.PositiveIntegerField(default=5)
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