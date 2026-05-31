from rest_framework import serializers
from .models import Profile

# write your serializers here
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['id', 'phone_number', 'full_name', 'delivery_address', 'created_at']
        read_only_fields = ['id', 'created_at']