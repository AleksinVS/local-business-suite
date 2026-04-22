from django.http import HttpResponse
import os


def debug_request(request):
    """Debug view to show request information"""
    lines = []
    lines.append("=== Request Information ===")
    lines.append(f"Path: {request.path}")
    lines.append(f"Path Info: {request.path_info}")
    lines.append(f"Script Name: {request.script_name}")
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
