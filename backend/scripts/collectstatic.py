"""One-shot build: isolated child environment, no runtime secrets or database."""

import os
from pathlib import Path
import secrets
import subprocess
import sys


BASE_DIR = Path(__file__).resolve().parent.parent


def build_environment(static_root):
    # Keep only OS execution/locale/temp settings, not Django, PostgreSQL,
    # storage credentials, PYTHONPATH or arbitrary runtime configuration.
    child_env = {
        name: os.environ[name]
        for name in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT')
        if name in os.environ
    }
    child_env.update({
        'DJANGO_SETTINGS_MODULE': 'config.settings',
        'DJANGO_STATIC_BUILD': 'True',
        'DJANGO_ENVIRONMENT': 'production',
        'DJANGO_DEBUG': 'False',
        'DJANGO_SECRET_KEY': secrets.token_urlsafe(64),
        'DJANGO_ALLOWED_HOSTS': 'localhost',
        'DJANGO_STATIC_ROOT': str(static_root),
        'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONUNBUFFERED': '1',
    })
    return child_env


def main():
    root = Path(os.environ.get('DJANGO_STATIC_ROOT', BASE_DIR / 'staticfiles'))
    if not root.is_absolute():
        root = BASE_DIR / root
    return subprocess.run(
        [sys.executable, 'manage.py', 'collectstatic', '--noinput'],
        cwd=BASE_DIR,
        env=build_environment(root),
        check=False,
    ).returncode


if __name__ == '__main__':
    raise SystemExit(main())
