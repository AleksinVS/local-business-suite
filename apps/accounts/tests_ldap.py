"""
Simple LDAP connection test for debugging
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, 'C:\\inetpub\\portal')
django.setup()

from apps.accounts.ldap_backend import LDAPConfig, ldap_connection

print("=== LDAP Connection Test ===")
print()

# Load config from environment
try:
    config = LDAPConfig.from_env()
    print("LDAP Configuration loaded:")
    print(f"  Host: {config.host}")
    print(f"  Port: {config.port}")
    print(f"  Transport: {config.transport}")
    print(f"  Allow Insecure: {config.allow_insecure}")
    print(f"  Verify Cert: {config.verify_cert}")
    print(f"  Service Account: {config.service_account}")
    print(f"  Search Base: {config.search_base}")
    print()

    # Test connection without binding
    print("Testing server connection...")
    import ldap3
    server = ldap3.Server(
        config.host,
        port=config.port,
        use_ssl=config.transport == "ldaps",
        get_info=None
    )
    conn = ldap3.Connection(server, auto_bind=False)
    conn.open()
    print(f"OK Connected to {config.host}:{config.port}")
    conn.unbind()
    print()

    # Test service account authentication
    print("Testing service account authentication...")
    if config.service_account and config.service_password:
        try:
            with ldap_connection(config, user=config.service_account, password=config.service_password) as conn:
                print(f"OK Service account authenticated successfully")
                print(f"  Bound as: {config.service_account}")
        except Exception as e:
            print(f"FAIL Service account authentication failed: {e}")
    else:
        print("SKIP Service account credentials not configured")

except Exception as e:
    print(f"FAIL Error: {e}")
    import traceback
    traceback.print_exc()

print()
print("=== Test Complete ===")
