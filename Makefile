PYTHON := ./.venv/bin/python
PYTHON_INSTALL := $(PYTHON) -m pip install
TEST_SCOPE ?=
TEST_FLAGS ?=

.PHONY: venv install lock lock-agent-runtime check test test-fast test-all contracts change-plan ai-runtime gen-struct

venv:
	python3 -m venv .venv

# Ставим зависимости из requirements.lock, а не из requirements.txt: lock
# фиксирует версии транзитивных зависимостей и делает установку
# воспроизводимой (тот же принцип, что и в Dockerfile).
install: venv
	$(PYTHON_INSTALL) -r requirements.lock

# Перегенерация requirements.lock из requirements.txt. Требует pip-tools
# (pip install pip-tools) — это dev-инструмент, поэтому он не добавлен в
# requirements.txt/requirements.lock как рантайм-зависимость.
lock:
	$(PYTHON) -m piptools compile --output-file=requirements.lock requirements.txt

# То же самое для отдельного lock-файла services/agent_runtime (собственный
# минимальный набор зависимостей этого сервиса, см. services/agent_runtime/Dockerfile).
lock-agent-runtime:
	$(PYTHON) -m piptools compile --output-file=services/agent_runtime/requirements.lock services/agent_runtime/requirements.txt

check:
	$(PYTHON) manage.py check
	$(PYTHON) manage.py check_staticfiles --fail

test:
	$(PYTHON) manage.py test $(TEST_SCOPE) $(TEST_FLAGS)

test-fast:
	$(PYTHON) manage.py test $(TEST_SCOPE) --keepdb $(TEST_FLAGS)

test-all:
	pytest --tb=short -q

contracts:
	$(PYTHON) manage.py validate_architecture_contracts

change-plan:
	$(PYTHON) manage.py generate_change_plan $(BRIEF) --output $(OUTPUT)

ai-runtime:
	uvicorn services.agent_runtime.app:app --host 0.0.0.0 --port 8090 --reload

gen-struct:
	node scripts/dev/generate-structure.js
