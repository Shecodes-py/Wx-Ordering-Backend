from django.urls import path, include
from rest_framework.routers import SimpleRouter
from . import views

router = SimpleRouter()
router.register('', views.PaymentViewSet, basename='payments')

urlpatterns = [
    path('webhook/squad/', views.squad_webhook, name='squad-webhook'),
    path('', include(router.urls)),
]