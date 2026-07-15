"""
Django settings for the Survey Kiosk project.

All deployment-specific values are read from the environment (optionally seeded
from a .env file in the project root). See .env.example for the full list.
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE_DIR = Path(__file__).resolve().parent.parent

# True while running the Django test suite. Used to skip HTTPS hardening that
# would otherwise make the (plain-HTTP) test client follow SSL redirects.
TESTING = "test" in sys.argv


def _load_dotenv(path):
    """Minimal .env loader: KEY=VALUE lines, no export, no interpolation."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return env(key, str(default)).lower() in ("1", "true", "yes", "on")


# --- Core -------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# Public base URL used to build absolute QR / magic links.
BASE_URL = env("BASE_URL", "http://localhost:8000").rstrip("/")
CSRF_TRUSTED_ORIGINS = [BASE_URL] if BASE_URL.startswith("https") else []


# --- Apps / middleware ------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "anymail",
    "django_htmx",
    "survey",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database ---------------------------------------------------------------
# Postgres in production via DATABASE_URL; SQLite fallback for local dev/tests.

def _parse_database_url(url):
    p = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(p.path.lstrip("/")),
        "USER": unquote(p.username or ""),
        "PASSWORD": unquote(p.password or ""),
        "HOST": p.hostname or "",
        "PORT": str(p.port or ""),
    }


_database_url = env("DATABASE_URL")
if _database_url:
    DATABASES = {"default": _parse_database_url(_database_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --- Auth / i18n ------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# --- Static / media ---------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Hashed+compressed manifest in production; plain storage in dev/tests
# (the manifest only exists after collectstatic).
_static_backend = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedManifestStaticFilesStorage"
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _static_backend},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Email (Postmark via Anymail) -------------------------------------------

if env("POSTMARK_SERVER_TOKEN"):
    EMAIL_BACKEND = "anymail.backends.postmark.EmailBackend"
    ANYMAIL = {"POSTMARK_SERVER_TOKEN": env("POSTMARK_SERVER_TOKEN")}
else:
    # Dev: print emails to the console until Postmark is configured.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Survey Kiosk <noreply@andrew.cmu.edu>")


# --- Security (hardened when DEBUG is off) ----------------------------------

if not DEBUG and not TESTING:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True


# --- Survey app config ------------------------------------------------------

TARGET_DOMAIN = env("TARGET_DOMAIN", "andrew.cmu.edu")
QR_ROTATE_SECONDS = int(env("QR_ROTATE_SECONDS", "5"))
TOKEN_TTL_SECONDS = int(env("TOKEN_TTL_SECONDS", "15"))
SURVEY_TTL_MINUTES = int(env("SURVEY_TTL_MINUTES", "20"))
VERIFY_TTL_HOURS = int(env("VERIFY_TTL_HOURS", "24"))

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
