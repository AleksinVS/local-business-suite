import os
from datetime import datetime
from django.conf import settings


class PathInfoDebugMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.log_file = "C:\\inetpub\\portal\\debug_path.log"
        self.debug = getattr(settings, "DEBUG", False)

    def __call__(self, request):
        # Fix IIS PATH_INFO issue - only apply if there's a clear mismatch
        request_uri = request.META.get("REQUEST_URI", "")
        path_info = request.META.get("PATH_INFO", "")

        # Only fix if PATH_INFO is clearly wrong:
        # 1. PATH_INFO is just '/'
        # 2. REQUEST_URI has a different path (not '/')
        # 3. REQUEST_URI is not empty
        # 4. We're not dealing with favicon or static files
        if (
            path_info == "/"
            and request_uri != "/"
            and request_uri
            and not request_uri.startswith("/favicon.")
            and not request_uri.startswith("/static/")
        ):
            # Extract path from REQUEST_URI (remove query string)
            path = request_uri.split("?")[0]

            # Only fix if the extracted path is valid
            if path and path.startswith("/"):
                # Update PATH_INFO and SCRIPT_NAME
                request.META["PATH_INFO"] = path
                request.META["SCRIPT_NAME"] = ""
                # Rebuild request.path
                request.path = path
                request.path_info = path

        # Only log in debug mode
        if self.debug:
            log_entry = f"{datetime.now()} - Path: {request.path} | Path Info: {request.path_info} | SCRIPT_NAME: {request.META.get('SCRIPT_NAME', '')} | PATH_INFO: {request.META.get('PATH_INFO')} | REQUEST_URI: {request.META.get('REQUEST_URI')}\n"

            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry)
            except Exception as e:
                pass

        response = self.get_response(request)
        return response
