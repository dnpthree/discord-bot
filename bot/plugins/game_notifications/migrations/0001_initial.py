# -*- coding: utf-8 -*-
# Generated by Django 1.9 on 2015-12-30 14:52
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='GameNotification',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('game_name', models.CharField(max_length=255, verbose_name='name')),
                ('user', models.CharField(max_length=255, verbose_name='user')),
            ],
        ),
    ]
