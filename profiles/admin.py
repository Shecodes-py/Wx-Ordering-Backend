from django.contrib import admin
from .models import Profile

# Register your models here.
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone_number', 'created_at')
    search_fields = ('full_name', 'phone_number')
    readonly_fields = ('created_at', 'updated_at')