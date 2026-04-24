"""
Сигналы для приложения accounts
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Сигнал для обработки создания/обновления пользователя.
    Используется для синхронизации с организационной структурой.
    """
    if created:
        # Логика при создании нового пользователя
        pass
    else:
        # Логика при обновлении пользователя
        pass
