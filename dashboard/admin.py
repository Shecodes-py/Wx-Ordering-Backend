from django.contrib import admin
from .models import MenuItem, Order, OrderItem, Feedback

# Register your models here.
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('unit_price',)


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'is_available', 'updated_at')
    list_filter = ('is_available',)
    search_fields = ('name',)
    list_editable = ('is_available',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'status', 'payment_method', 'payment_status', 'total_price', 'created_at')
    list_filter = ('status', 'payment_method', 'payment_status')
    search_fields = ('customer__full_name', 'customer__phone_number')
    readonly_fields = ('total_price', 'squad_transaction_ref', 'created_at', 'updated_at')
    inlines = [OrderItemInline]


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('customer', 'order', 'created_at')
    search_fields = ('customer__full_name', 'message')
    readonly_fields = ('created_at',)