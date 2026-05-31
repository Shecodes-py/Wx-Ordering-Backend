from django.urls import path
from . import views

urlpatterns = [
    path('webhook/squad/', views.squad_webhook, name='squad-webhook'),
]