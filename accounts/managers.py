from django.contrib.auth.models import UserManager as DjangoUserManager


class UserManager(DjangoUserManager):
    """Keep Django user creation, with a consistent application superuser role."""

    def _superuser_fields(self, extra_fields):
        from .models import Role

        extra_fields.setdefault("role", Role.SUPER_ADMIN)
        if extra_fields["role"] != Role.SUPER_ADMIN:
            raise ValueError("Superuser must have role=SUPER_ADMIN.")
        return extra_fields

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        return super().create_superuser(
            username, email, password, **self._superuser_fields(extra_fields)
        )

    create_superuser.alters_data = True

    async def acreate_superuser(self, username, email=None, password=None, **extra_fields):
        return await super().acreate_superuser(
            username, email, password, **self._superuser_fields(extra_fields)
        )

    acreate_superuser.alters_data = True
