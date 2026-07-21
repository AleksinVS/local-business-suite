from django.contrib.auth.views import LoginView, LogoutView


MANUAL_AUTH_SESSION_KEY = "local_business_manual_auth"


class PortalLoginView(LoginView):
    """Manual login must take precedence over REMOTE_USER for this session."""

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session[MANUAL_AUTH_SESSION_KEY] = True
        return response


class PortalLogoutView(LogoutView):
    """Logout must leave the user anonymous even when REMOTE_USER is present."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        request.session[MANUAL_AUTH_SESSION_KEY] = True
        return response
