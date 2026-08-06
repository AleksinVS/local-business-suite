from django.contrib.auth.middleware import PersistentRemoteUserMiddleware

from apps.core.middleware import is_automatic_public_request

from .views import MANUAL_AUTH_SESSION_KEY


class ManualAuthAwareRemoteUserMiddleware(PersistentRemoteUserMiddleware):
    """Skip REMOTE_USER auto-login after a manual login or logout."""

    def process_request(self, request):
        # Браузер может запросить favicon/service worker параллельно с первым
        # HTML-документом. SSO на таком запросе создаст вторую сессию и второй
        # CSRF-секрет; последний Set-Cookie тогда сделает токен формы неверным.
        # Канонически favicon исключается в IIS, а эта проверка защищает старые
        # web.config и прочие публичные служебные ресурсы.
        if request.session.get(MANUAL_AUTH_SESSION_KEY) or is_automatic_public_request(request):
            return
        return super().process_request(request)
