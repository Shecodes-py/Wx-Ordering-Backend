from django.db import models

# Create your models here.

class Profile(models.Model):
    phone_number = models.CharField(max_length=20, unique=True)
    full_name = models.CharField(max_length=100)
    delivery_address = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name