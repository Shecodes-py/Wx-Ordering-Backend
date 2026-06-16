from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register('menu', views.MenuItemViewSet, basename='menu')
router.register('orders', views.OrderViewSet, basename='orders')
router.register('feedback', views.FeedbackViewSet, basename='feedback')

urlpatterns = [
    path('menu/public/', views.PublicMenuView.as_view(), name='menu-public'),
    path('analytics/', views.AnalyticsView.as_view(), name='analytics'),
    path('orders/stream/', views.OrderStreamView.as_view(), name='orders-stream'),
    path('', include(router.urls)),
]