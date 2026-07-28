from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from .models import Role

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="secure-password-123",
        )
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(user.role, Role.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="secure-password-123",
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_password_is_hashed(self):
        plain = "secure-password-123"
        user = User.objects.create_user(
            username="bob",
            email="bob@example.com",
            password=plain,
        )
        self.assertNotEqual(user.password, plain)
        self.assertTrue(user.check_password(plain))

    def test_email_must_be_unique(self):
        User.objects.create_user(
            username="first",
            email="shared@example.com",
            password="secure-password-123",
        )
        with self.assertRaises(IntegrityError):
            User.objects.create_user(
                username="second",
                email="shared@example.com",
                password="secure-password-123",
            )

    def test_default_role_is_customer(self):
        user = User.objects.create_user(
            username="carol",
            email="carol@example.com",
            password="secure-password-123",
        )
        self.assertEqual(user.role, Role.CUSTOMER)
