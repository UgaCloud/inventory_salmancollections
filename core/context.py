from .models import ShopSettings
from .permissions import user_permissions


def app_context(request):
    settings_obj = ShopSettings.load()
    perms = user_permissions(request.user) if request.user.is_authenticated else set()
    return {
        "shop": settings_obj,
        "perms": perms,
        "currency_symbol": settings_obj.currency_symbol,
    }
