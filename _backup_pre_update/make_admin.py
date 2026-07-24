#!/usr/bin/env python
"""
Script to create user aleksin.vs and make him administrator
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User

def make_aleksin_vs_admin():
    """Create or update user aleksin.vs and make him administrator"""
    username = 'aleksin.vs'

    # Find or create user
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': 'aleksin.vs@mscher.local',
            'first_name': 'Aleksin',
            'last_name': 'VS',
            'is_staff': True,
            'is_superuser': True,
            'is_active': True
        }
    )

    if created:
        print(f"[OK] User {username} created")
    else:
        print(f"[INFO] User {username} already exists")

    # Set admin rights
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.save()

    print(f"[OK] User {username} is now administrator")
    print(f"   - is_staff: {user.is_staff}")
    print(f"   - is_superuser: {user.is_superuser}")
    print(f"   - is_active: {user.is_active}")

    # Create ExternalIdentity for LDAP authentication
    from apps.accounts.models import ExternalIdentity

    ext_identity, created = ExternalIdentity.objects.get_or_create(
        user=user,
        provider='active_directory',
        defaults={
            'username': username,
            'domain': 'MSCHER',
            'sync_status': 'verified'
        }
    )

    if created:
        print(f"[OK] ExternalIdentity for LDAP created")
    else:
        ext_identity.sync_status = 'verified'
        ext_identity.save()
        print(f"[INFO] ExternalIdentity updated")

    print(f"\n[DONE] User {username} can now:")
    print(f"   - Login via Windows credentials (SSO)")
    print(f"   - Access Django Admin")
    print(f"   - Have full administrative rights")

if __name__ == '__main__':
    make_aleksin_vs_admin()
