from rest_framework import serializers
from cloudinary import uploader
from .models import MenuItem, Order, OrderItem, Feedback


def _validate_image_size(file):
    max_bytes = 5 * 1024 * 1024
    if file.size > max_bytes:
        raise serializers.ValidationError("Image must be 5 MB or smaller.")
    return file


class MenuItemSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(write_only=True, required=False, validators=[_validate_image_size])

    class Meta:
        model = MenuItem
        fields = ['id', 'name', 'description', 'price', 'image', 'image_url', 'is_available', 'created_at', 'updated_at']
        read_only_fields = ['id', 'image_url', 'created_at', 'updated_at']

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def _upload_image(self, image_file):
        if not image_file:
            return None
        result = uploader.upload(image_file, folder='wx_menu')
        return result['secure_url']

    def create(self, validated_data):
        image_file = validated_data.pop('image', None)
        validated_data['image_url'] = self._upload_image(image_file)
        return MenuItem.objects.create(**validated_data)

    def update(self, instance, validated_data):
        image_file = validated_data.pop('image', None)
        if image_file:
            validated_data['image_url'] = self._upload_image(image_file)
        return super().update(instance, validated_data)


class OrderItemSerializer(serializers.ModelSerializer):
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)
    subtotal = serializers.SerializerMethodField()
    menu_item_name = serializers.CharField(source='menu_item.name', read_only=True)
    menu_item_image = serializers.URLField(source='menu_item.image_url', read_only=True)
    subtotal = serializers.SerializerMethodField()


    class Meta:
        model = OrderItem
        fields = ['id', 'menu_item', 'menu_item_name', 'quantity', 'unit_price', 'subtotal',
                  'menu_item_image',
                  ]
        read_only_fields = ['id', 'menu_item_name', 'menu_item_image', 'subtotal']

    def get_subtotal(self, obj):
        return obj.subtotal

    
class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    customer_address = serializers.CharField(source='customer.delivery_address', read_only=True)
    chat_started = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone', 'customer_address',
            'items', 'status', 'payment_method', 'payment_status', 'total_price',
            'squad_transaction_ref','chat_started', 'created_at', 'updated_at',]
        read_only_fields = [
            'id', 'customer_name', 'customer_phone', 'customer_address',
            'items', 'total_price', 'squad_transaction_ref', 'chat_started', 'created_at', 'updated_at',
        ]
    def get_chat_started(self, obj):
        try:
            return obj.customer.bot_session.created_at
        except Exception:
            return None

class FeedbackSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)

    class Meta:
        model = Feedback
        fields = ['id', 'order', 'customer', 'customer_name', 'customer_phone', 'message', 'created_at','rating']
        read_only_fields = ['id', 'customer_name', 'customer_phone', 'created_at']

    def validate_rating(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError("Ratings must be between 1 and 5.")
        return value
    
    # # def review_flag(self, obj):
        