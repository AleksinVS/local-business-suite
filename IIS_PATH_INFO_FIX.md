# IIS FastCGI PATH_INFO Issue Resolution

## Problem

When deploying Django applications on IIS with FastCGI (wfastcgi), all internal pages (`/workorders/`, `/inventory/`, `/analytics/`, etc.) redirect to the homepage instead of showing the correct content.

## Root Cause

IIS FastCGI incorrectly passes the `PATH_INFO` environment variable to Django. Instead of the correct path (`/workorders/`), Django receives only `/`:

```
REQUEST_URI: /workorders/  (correct)
PATH_INFO: /              (incorrect!)
SCRIPT_NAME:
```

Django uses `PATH_INFO` for URL routing, so it thinks the user is on the homepage (`/`) and displays the homepage content instead of the intended page.

## Detection

You can detect this issue by:

1. Observing that all internal pages show homepage content
2. Checking IIS logs show 200 OK responses (not 404 or 301/302 redirects)
3. Adding debug middleware shows mismatch between `PATH_INFO` and `REQUEST_URI`

## Solution

The project includes `PathInfoDebugMiddleware` in `apps/core/middleware.py` that automatically fixes this issue:

### How It Works

1. Detects mismatch between `PATH_INFO` and `REQUEST_URI`
2. If `PATH_INFO` is `/` but `REQUEST_URI` contains a different path:
   - Extracts the correct path from `REQUEST_URI`
   - Updates `PATH_INFO` and `SCRIPT_NAME` in the request
   - Rebuilds `request.path` and `request.path_info`
3. Only applies fix when there's a clear mismatch
4. Safe for other web servers (Apache, Nginx, Gunicorn)

### Configuration

Middleware is already configured in `config/settings.py`:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.core.middleware.PathInfoDebugMiddleware",  # <-- IIS PATH_INFO fix
    "django.middleware.common.CommonMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

### Additional Settings

Added `FORCE_SCRIPT_NAME = ""` in `config/settings.py` for IIS compatibility.

## Verification

### Debug Logging

In DEBUG mode (`DJANGO_DEBUG=1`), the middleware writes logs to `C:\inetpub\portal\debug_path.log`:

```
2026-04-22 14:22:04.673730 - Path: /workorders/ | Path Info: /workorders/ | SCRIPT_NAME:  | PATH_INFO: /workorders/ | REQUEST_URI: /workorders/
```

### Testing

1. Navigate to internal pages: `/workorders/`, `/inventory/`, `/analytics/`
2. Verify correct content is displayed (not homepage)
3. Check debug logs show corrected `PATH_INFO`

## Important Notes

1. **Python Version Compatibility**: Use Python 3.11.9 (3.13+ is incompatible with wfastcgi 3.0.0)
2. **Safe for Other Web Servers**: Middleware only activates when there's a clear mismatch
3. **Production Ready**: Debug logging is disabled in production
4. **IIS Configuration**: Ensure `allowPathInfo="true"` is set in web.config handler

## Alternative Solutions

If middleware approach doesn't work, consider:

1. **URL Rewrite Module**: Configure IIS URL Rewrite rules
2. **Different FastCGI Setup**: Try different FastCGI configuration
3. **Alternative Web Server**: Consider using Caddy or Nginx as reverse proxy

However, the middleware approach is recommended as it's Django-specific and server-agnostic.

## References

- IIS FastCGI Configuration: `web.config`
- Middleware Implementation: `apps/core/middleware.py`
- Django Settings: `config/settings.py`
- IIS SSO Documentation: `IIS_SSO.md`
