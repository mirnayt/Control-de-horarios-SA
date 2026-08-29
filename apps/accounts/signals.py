from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .roles import ALL_ROLES


@receiver(post_migrate)
def create_role_groups(sender, **kwargs):
    if sender.name != "apps.accounts":
        return
    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)
