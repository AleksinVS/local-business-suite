from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse
import os


@staff_member_required
def debug_request(request):
    """Debug view to show request information.

    Регистрируется в ``apps/core/urls.py`` только при ``DEBUG`` и
    ``LOCAL_BUSINESS_IIS_COMPAT_ENABLED=true`` — не регистрируется вовсе (404)
    в обычной эксплуатации, т.к. выводит переменные окружения процесса.
    """
    lines = []
    lines.append("=== Request Information ===")
    lines.append(f"Path: {request.path}")
    lines.append(f"Path Info: {request.path_info}")
    lines.append(f"Script Name: {request.META.get('SCRIPT_NAME', '')}")
    lines.append(f"Method: {request.method}")
    lines.append(f"GET: {request.GET}")
    lines.append(f"POST: {request.POST}")
    lines.append(f"Meta:")
    for key, value in sorted(request.META.items()):
        if (
            key.startswith("PATH")
            or key.startswith("SCRIPT")
            or key.startswith("HTTP")
            or key in ["REQUEST_URI", "QUERY_STRING", "REMOTE_USER"]
        ):
            lines.append(f"  {key}: {value}")
    lines.append("\n=== Environment Variables ===")
    for key in sorted(os.environ.keys()):
        if (
            key.startswith("PATH")
            or key.startswith("SCRIPT")
            or key.startswith("WSGI")
            or key in ["REQUEST_URI", "QUERY_STRING", "REMOTE_USER"]
        ):
            lines.append(f"{key}: {os.environ.get(key)}")

    return HttpResponse("<pre>" + "\n".join(lines) + "</pre>")
