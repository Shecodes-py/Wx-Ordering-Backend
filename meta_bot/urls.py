from django.urls import path
from .views import MetaWebhookView

urlpatterns = [
    path('webhook/', MetaWebhookView.as_view(), name='meta-webhook'),
]
