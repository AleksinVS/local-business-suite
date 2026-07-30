PYTHON := ./.venv/bin/python
PYTHON_INSTALL := $(PYTHON) -m pip install
PYTEST := $(PYTHON) -m pytest
TEST_SCOPE ?=
TEST_FLAGS ?=

.PHONY: venv install install-dev lock lock-dev lock-agent-runtime check test test-fast test-failed test-profile test-unit test-integration test-parallel test-all contracts change-plan ai-runtime gen-struct

venv:
	python3 -m venv .venv

# Ставим зависимости из requirements.lock, а не из requirements.txt: lock
# фиксирует версии транзитивных зависимостей и делает установку
# воспроизводимой (тот же принцип, что и в Dockerfile).
install: venv
	$(PYTHON_INSTALL) -r requirements.lock

install-dev: venv
	$(PYTHON_INSTALL) -r requirements-dev.lock

# Перегенерация requirements.lock из requirements.txt. Требует pip-tools
# (pip install pip-tools) — это dev-инструмент, поэтому он не добавлен в
# requirements.txt/requirements.lock как рантайм-зависимость.
lock:
	$(PYTHON) -m piptools compile --output-file=requirements.lock requirements.txt

lock-dev:
	$(PYTHON) -m piptools compile --output-file=requirements-dev.lock requirements-dev.txt

# То же самое для отдельного lock-файла services/agent_runtime (собственный
# минимальный набор зависимостей этого сервиса, см. services/agent_runtime/Dockerfile).
lock-agent-runtime:
	$(PYTHON) -m piptools compile --output-file=services/agent_runtime/requirements.lock services/agent_runtime/requirements.txt

check:
	$(PYTHON) manage.py check
	$(PYTHON) manage.py check_staticfiles --fail

test:
	$(PYTEST) $(TEST_SCOPE) --migrations --create-db $(TEST_FLAGS)

test-fast:
	$(PYTEST) $(TEST_SCOPE) --reuse-db --maxfail=1 $(TEST_FLAGS)

test-failed:
	$(PYTEST) $(TEST_SCOPE) --last-failed --last-failed-no-failures=none --reuse-db --maxfail=1 $(TEST_FLAGS)

test-profile:
	$(PYTEST) $(TEST_SCOPE) --reuse-db --durations=25 --durations-min=0.25 $(TEST_FLAGS)

test-unit:
	$(PYTEST) $(TEST_SCOPE) --reuse-db -m unit $(TEST_FLAGS)

test-integration:
	$(PYTEST) $(TEST_SCOPE) --reuse-db -m integration $(TEST_FLAGS)

# Экспериментальный запуск: применять только после зеленого последовательного
# прогона и проверки отсутствия конфликтов файловых/контрактных тестов.
test-parallel:
	$(PYTEST) $(TEST_SCOPE) --reuse-db -n auto --dist loadscope $(TEST_FLAGS)

test-all: test

contracts:
	$(PYTHON) manage.py validate_architecture_contracts

change-plan:
	$(PYTHON) manage.py generate_change_plan $(BRIEF) --output $(OUTPUT)

ai-runtime:
	uvicorn services.agent_runtime.app:app --host 0.0.0.0 --port 8090 --reload

gen-struct:
	node scripts/dev/generate-structure.js
