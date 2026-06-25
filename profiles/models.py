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


# class BusinessSettings(models.Model):
#     business_name = models.CharField(max_length=100, default="My Business")
#     business_address = models.TextField(default="123 Main St, City, Country")
#     contact_email = models.EmailField(default="")
#     phone_number = models.CharField(max_length=20, default="")
#     operating_hours = models.CharField(max_length=100, default="Mon-Fri 9am-5pm")
#     accepting_orders = models.BooleanField(default=True)    
#     description = models.TextField()
#     business_id = models.CharField(max_length=100)
#     account_number = models.IntegerField()
#     bank_name = models.CharField(max_length=100)

#     #notification settings
