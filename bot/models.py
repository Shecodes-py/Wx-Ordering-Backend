from django.db import models
from profiles.models import Profile

# Create your models here.

class BotSession(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name='bot_session')
    state = models.CharField(max_length=50, default='START')
    cart = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Session — {self.profile.phone_number} ({self.state})"