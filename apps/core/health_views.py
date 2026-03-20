from django.http import JsonResponse


def health_check(request):
    """
    Health check endpoint for Docker health check.
    Returns 200 OK if the application is running.
    """
    return JsonResponse({"status": "ok", "service": "local-business-suite"})
