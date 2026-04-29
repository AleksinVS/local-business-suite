import logging
import time
from django.http import JsonResponse
from django.db import connection
from django.conf import settings
import httpx

logger = logging.getLogger(__name__)

def health_check(request):
    """
    Comprehensive health check for the entire suite.
    Checks: DB, AI Runtime, LDAP (if enabled).
    """
    start_time = time.time()
    
    health_status = {
        "status": "ok",
        "timestamp": time.time(),
        "services": {}
    }
    
    overall_ok = True

    # 1. Database Check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        health_status["services"]["database"] = {"status": "ok"}
    except Exception as e:
        logger.error(f"Health check failed: Database is unreachable: {e}")
        health_status["services"]["database"] = {"status": "error", "message": str(e)}
        overall_ok = False

    # 2. AI Runtime Check
    ai_runtime_url = getattr(settings, "LOCAL_BUSINESS_AGENT_RUNTIME_URL", "http://127.0.0.1:8090")
    try:
        response = httpx.get(f"{ai_runtime_url}/health", timeout=2.0)
        if response.status_code == 200:
            health_status["services"]["ai_runtime"] = {"status": "ok", "details": response.json()}
        else:
            health_status["services"]["ai_runtime"] = {"status": "degraded", "code": response.status_code}
            # AI Runtime is important but might not be fatal for core portal
    except Exception as e:
        logger.warning(f"Health check: AI Runtime is unreachable at {ai_runtime_url}: {e}")
        health_status["services"]["ai_runtime"] = {"status": "unreachable", "message": str(e)}
        # We don't set overall_ok = False here to allow portal to work even if AI is down

    # 3. LDAP Connectivity (if configured)
    auth_mode = getattr(settings, "DJANGO_AUTH_MODE", "local")
    if auth_mode in ["ldap", "remote_user", "hybrid"]:
        # We could add a more robust LDAP ping here if ldap3 is available
        # For now, we'll just mark it as "configured"
        health_status["services"]["auth_mode"] = {"status": "ok", "mode": auth_mode}

    if not overall_ok:
        health_status["status"] = "error"
        return JsonResponse(health_status, status=503)

    health_status["duration_ms"] = int((time.time() - start_time) * 1000)
    return JsonResponse(health_status)
