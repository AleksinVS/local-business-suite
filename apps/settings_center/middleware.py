"""HTTP middleware for request-local settings document snapshots."""

from .document_repository import (
    ConfigDocumentRepository,
    activate_repository,
    reset_repository,
)


class ConfigDocumentRequestMiddleware:
    """Keep effective runtime documents consistent during one HTTP request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        repository = ConfigDocumentRepository()
        # Explicit ``request=`` calls can reuse the same repository too;
        # request-less get_contract calls use the ContextVar below.
        request._config_document_repository = repository
        request._config_document_snapshots = repository._request_snapshots
        token = activate_repository(repository)
        try:
            return self.get_response(request)
        finally:
            # Reset even when the view or another middleware raises.
            reset_repository(token)
