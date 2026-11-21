from django.contrib.auth.models import User

from .models import Role, StaffProfile


def make_staff(username, role_slug=None, password="test-pass-123", superuser=False):
    user = User.objects.create_user(
        username=username,
        password=password,
        is_staff=superuser,
        is_superuser=superuser,
    )
    profile, _ = StaffProfile.objects.get_or_create(user=user)
    if role_slug:
        profile.role = Role.objects.get(slug=role_slug)
    profile.is_active = True
    profile.save()
    return user
