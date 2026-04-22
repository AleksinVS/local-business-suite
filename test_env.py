import os
import sys

# Add project to path
sys.path.insert(0, "C:/inetpub/portal")

# Load environment variables
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path("C:/inetpub/portal/.env"))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()

# Print environment variables that are important for URL routing
print("=== Environment Variables ===")
for key in ["PATH_INFO", "SCRIPT_NAME", "REQUEST_URI", "QUERY_STRING", "REMOTE_USER"]:
    value = os.environ.get(key, "NOT SET")
    print(f"{key}: {value}")

print("\n=== Django Settings ===")
from django.conf import settings

print(f"FORCE_SCRIPT_NAME: {settings.FORCE_SCRIPT_NAME}")
print(f"APPEND_SLASH: {settings.APPEND_SLASH}")
print(f"USE_X_FORWARDED_HOST: {settings.USE_X_FORWARDED_HOST}")
print(f"ALLOWED_HOSTS: {settings.ALLOWED_HOSTS}")
