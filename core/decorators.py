from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .permissions import user_permissions


def perm_required(*codes):
    """Require every given feature permission, checked on the server."""

    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            perms = user_permissions(request.user)
            if not all(code in perms for code in codes):
                raise PermissionDenied("You do not have permission to do that.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


def perm_required_any(*codes):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            perms = user_permissions(request.user)
            if not any(code in perms for code in codes):
                raise PermissionDenied("You do not have permission to do that.")
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
