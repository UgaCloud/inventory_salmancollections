from .general import *
from decouple import config


DEBUG = True

ALLOWED_HOSTS = [salmancollections.com]

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production-!@#$%^&*()')

INTERNAL_IPS = [
    "127.0.0.1",
]

def show_toolbar(request):
    return True

DEBUG_TOOLBAR_CONFIG = {
  "SHOW_TOOLBAR_CALLBACK" : show_toolbar,
}

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        # 'ENGINE': 'django.db.backends.sqlite3',
        # 'NAME': BASE_DIR / 'db.sqlite3',

        'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'salmvbej_inventory',
        'USER': 'salmvbej_user',
        'PASSWORD': '_nNJnt+0JT5sO[Wb',
        'HOST': 'localhost',
        'PORT': '3306',
    }
    }
}
