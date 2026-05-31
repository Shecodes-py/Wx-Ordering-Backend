from django.shortcuts import render
from rest_framework.generics import ListAPIView, RetrieveAPIView
from .models import Profile
from .serializers import ProfileSerializer

# Create your views here.
def index(request):
    return render(request, 'index.html')

class ProfileListView(ListAPIView):
    queryset = Profile.objects.all().order_by('-created_at')
    serializer_class = ProfileSerializer

class ProfileDetailView(RetrieveAPIView):
    queryset = Profile.objects.all()
    serializer_class = ProfileSerializer