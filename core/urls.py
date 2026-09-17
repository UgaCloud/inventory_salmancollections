# from django.contrib import admin
# from django.urls import path, include
# from debug_toolbar.toolbar import debug_toolbar_urls

# urlpatterns = [
#     path('admin/', admin.site.urls),
#     path('', include('app.urls')),
#     path('api/', include('api.urls')),
# ] + debug_toolbar_urls()

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('app.urls')),
    path('api/', include('api.urls')),
]

# Only enable Debug Toolbar locally when DEBUG is True
if settings.DEBUG:
    try:
        from debug_toolbar.toolbar import debug_toolbar_urls
        urlpatterns += debug_toolbar_urls()
    except ImportError:
        pass
