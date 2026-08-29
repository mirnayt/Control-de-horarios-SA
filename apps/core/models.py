from django.db import models


class TimeStampedModel(models.Model):
    """Mixin abstracto para auditoría básica."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
