from django.db import models
from profiles.models import Profile

# Create your models here.

class BotSession(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name='bot_session')
    state = models.CharField(max_length=50, default='START')
    cart = models.JSONField(default=dict)
    # AI-extracted fields persisted across turns
    notes = models.TextField(blank=True, default='')
    extracted_address = models.TextField(blank=True, default='')
    payment_method = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session — {self.profile.phone_number} ({self.state})"

    def reset(self):
        """Clear all ordering state after a completed or cancelled order."""
        self.state = 'START'
        self.cart = {}
        self.notes = ''
        self.extracted_address = ''
        self.payment_method = ''
        self.save(update_fields=['state', 'cart', 'notes', 'extracted_address', 'payment_method'])