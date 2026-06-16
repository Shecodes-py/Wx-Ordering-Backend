from django.urls import path
from . import views

# write your urls here
urlpatterns = [
    # path('', views.ProfileListView.as_view(), name='profile-list'),
    path('<int:pk>/', views.ProfileDetailView.as_view(), name='profile-detail'),
]