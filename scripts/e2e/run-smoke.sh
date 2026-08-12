#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_root"

e2e_port="${E2E_PORT:-8001}"
if [[ ! "$e2e_port" =~ ^[0-9]+$ ]]; then
  echo "E2E_PORT должен быть числом" >&2
  exit 2
fi

mkdir -p .local
artifact_dir="${E2E_ARTIFACT_DIR:-$(mktemp -d "$project_root/.local/e2e-smoke-XXXXXX")}"
mkdir -p "$artifact_dir"

export LOCAL_BUSINESS_SQLITE_PATH="${LOCAL_BUSINESS_SQLITE_PATH:-$artifact_dir/e2e.sqlite3}"
export E2E_USERNAME="${E2E_USERNAME:-local-e2e}"
export E2E_PASSWORD="${E2E_PASSWORD:-local-e2e-ephemeral-password}"
export E2E_ACCESS_TARGET_USERNAME="${E2E_ACCESS_TARGET_USERNAME:-local-e2e-target}"
export E2E_BASE_URL="http://127.0.0.1:$e2e_port"
e2e_python="${E2E_PYTHON:-./.venv/bin/python}"

"$e2e_python" manage.py migrate --noinput > "$artifact_dir/migrate.log"
"$e2e_python" manage.py seed_roles > "$artifact_dir/seed-roles.log"
"$e2e_python" manage.py shell -c "import os; from django.contrib.auth import get_user_model; User=get_user_model(); username=os.environ['E2E_USERNAME']; target=os.environ['E2E_ACCESS_TARGET_USERNAME']; User.objects.filter(username__in=[username, target]).delete(); User.objects.create_superuser(username=username, email='e2e@example.invalid', password=os.environ['E2E_PASSWORD']); User.objects.create_user(username=target, email='target@example.invalid')" > "$artifact_dir/seed.log"
"$e2e_python" manage.py runserver "127.0.0.1:$e2e_port" --noreload > "$artifact_dir/server.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT

for attempt in $(seq 1 30); do
  if curl --fail --silent "$E2E_BASE_URL/health/" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent "$E2E_BASE_URL/health/" >/dev/null

npm run test:e2e:smoke
echo "E2E artifacts: ${artifact_dir#$project_root/}"
