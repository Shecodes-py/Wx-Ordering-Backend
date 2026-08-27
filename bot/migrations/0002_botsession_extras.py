from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='botsession',
            name='notes',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='botsession',
            name='extracted_address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='botsession',
            name='payment_method',
            field=models.CharField(blank=True, default='', max_length=20),
        ),
    ]
