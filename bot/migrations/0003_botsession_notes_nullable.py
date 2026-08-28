from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0002_botsession_extras'),
    ]

    operations = [
        migrations.AlterField(
            model_name='botsession',
            name='notes',
            field=models.TextField(blank=True, null=True, default=None),
        ),
    ]
