from django.contrib.auth.middleware import PersistentRemoteUserMiddleware

from .views import MANUAL_AUTH_SESSION_KEY


class ManualAuthAwareRemoteUserMiddleware(PersistentRemoteUserMiddleware):
    """Skip REMOTE_USER auto-login after a manual login or logout."""

    def process_request(self, request):
        if request.session.get(MANUAL_AUTH_SESSION_KEY):
            return
        return super().process_request(request)
