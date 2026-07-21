"""
Debug script to reload Python modules in wfastcgi
"""
import sys

# Force reload of all modules
modules_to_reload = [name for name in sys.modules if name.startswith('apps.accounts')]
for module_name in modules_to_reload:
    if module_name in sys.modules:
        del sys.modules[module_name]
        print(f"Removed {module_name} from cache")

# Now import normally
from django.core.wsgi import get_wsgi_application
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
application = get_wsgi_application()

print("WSGI application reloaded with module cache cleared")
