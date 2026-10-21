import django.db.models.deletion
from django.db import migrations, models

import apps.sites.models
from apps.core.rls import enable_rls_operation


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_showcase'),
        ('sites', '0005_sitelinecontent_considerations'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitelinecontent',
            name='cover',
            field=models.ImageField(blank=True, help_text='تصویر بزرگ بالای صفحه (افقی، حداقل ۱۲۰۰ پیکسل عرض). حداکثر ۳ مگابایت.', upload_to='lines/', validators=[apps.sites.models.validate_image_size], verbose_name='تصویر شاخص'),
        ),
        migrations.AddField(
            model_name='sitelinecontent',
            name='cover_alt',
            field=models.CharField(blank=True, max_length=120, verbose_name='توضیح تصویر شاخص'),
        ),
        migrations.AddField(
            model_name='sitelinecontent',
            name='highlights',
            field=models.TextField(blank=True, help_text='هر خط یک نکتهٔ کوتاه؛ مثل «پاسخ در همان روز کاری». حداکثر ۶ مورد نمایش داده می\u200cشود.', verbose_name='نکات برجسته'),
        ),
        migrations.CreateModel(
            name='SiteLineImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='lines/gallery/', validators=[apps.sites.models.validate_image_size], verbose_name='تصویر')),
                ('caption', models.CharField(blank=True, max_length=120, verbose_name='شرح تصویر')),
                ('order', models.PositiveIntegerField(default=0, verbose_name='ترتیب')),
                ('content', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='sites.sitelinecontent', verbose_name='محتوای رشته')),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='core.tenant', verbose_name='محیط')),
            ],
            options={
                'verbose_name': 'تصویر رشته',
                'verbose_name_plural': 'تصاویر رشته\u200cها',
                'ordering': ['order', 'id'],
            },
        ),
        enable_rls_operation("sites_sitelineimage"),
    ]
