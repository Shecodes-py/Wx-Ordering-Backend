from django.urls import path
from . import views

urlpatterns = [
    path('webhook/', views.WhatsAppWebhookView.as_view(), name='whatsapp-webhook'),
]