# -*- coding: utf-8 -*-
# Generated by Django 1.9.1 on 2016-05-08 14:48
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_member_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='member',
            name='last_seen',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]