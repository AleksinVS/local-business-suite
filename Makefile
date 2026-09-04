PYTHON := ./.venv/bin/python
PYTHON_INSTALL := $(PYTHON) -m pip install
PYTEST := $(PYTHON) -m pytest
TEST_SCOPE ?=
TEST_FLAGS ?=
TEST_WORKERS ?= auto

.PHONY: venv install install-dev lock lock-dev lock-agent-runtime check check-fast test test-fast test-failed test-profile test-unit test-integration test-parallel test-all test-db-reset verify-fast verify-profile verify-full contracts change-plan ai-runtime gen-struct

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

check-fast:
	$(PYTHON) manage.py check
	git diff --check

test:
	$(PYTEST) $(TEST_SCOPE) --migrations --create-db $(TEST_FLAGS)

test-fast:
	$(PYTEST) $(TEST_SCOPE) --reuse-db --maxfail=1 $(TEST_FLAGS)

test-failed:
	$(PYTEST) $(TEST_SCOPE) --last-failed --last-failed-no-failures=none --reuse-db --maxfail=1 $(TEST_FLAGS)

test-profile:
	$(PYTEST) $(TEST_SCOPE) --reuse-db --durations=25 --durations-min=0.25 $(TEST_FLAGS)

test-unit:
	$(PYTEST) $(TEST_SCOPE) -m unit $(TEST_FLAGS)

test-integration:
	$(PYTEST) $(TEST_SCOPE) --reuse-db -m integration $(TEST_FLAGS)

# Параллельные workers никогда не получают serial-тесты. Они выполняются
# отдельным последовательным проходом после успешной параллельной части.
test-parallel:
	@set +e; $(PYTEST) $(TEST_SCOPE) --reuse-db -n $(TEST_WORKERS) --dist loadscope -m "not serial" $(TEST_FLAGS); status=$$?; if [ $$status -ne 0 ] && [ $$status -ne 5 ]; then exit $$status; fi
	@set +e; $(PYTEST) $(TEST_SCOPE) --reuse-db -m serial $(TEST_FLAGS); status=$$?; if [ $$status -ne 0 ] && [ $$status -ne 5 ]; then exit $$status; fi

test-all: test

test-db-reset:
	$(PYTHON) scripts/dev/reset-test-database.py

# Короткий внутренний цикл: системная проверка и минимальный затронутый scope.
verify-fast: check-fast
	@test -n "$(TEST_SCOPE)" || (echo "Укажите TEST_SCOPE=<pytest-path>" >&2; exit 2)
	$(PYTEST) $(TEST_SCOPE) --reuse-db --maxfail=1 -m "not slow" $(TEST_FLAGS)

# Профили фиксируют типовые связи модулей, чтобы не собирать команды вручную.
verify-profile: check-fast
	@case "$(PROFILE)" in \
		ai) $(MAKE) test-fast TEST_SCOPE="apps/ai services/agent_runtime/tests" && $(MAKE) contracts ;; \
		memory) $(MAKE) test-fast TEST_SCOPE="apps/memory apps/filehub" && $(MAKE) contracts ;; \
		ui) $(MAKE) test-fast TEST_SCOPE="apps/ai/tests apps/notifications/tests.py apps/workorders/tests.py" && bash scripts/e2e/run-smoke.sh ;; \
		contracts) $(MAKE) contracts && $(MAKE) test-fast TEST_SCOPE="apps/core/tests.py services/agent_runtime/tests" TEST_FLAGS="-k Contract" ;; \
		deployment) $(MAKE) test-fast TEST_SCOPE="apps/core/tests.py" TEST_FLAGS="-k 'Iis or Staticfiles or Bootstrap or DatabaseConfig'" ;; \
		*) echo "Неизвестный PROFILE=$(PROFILE). Допустимо: ai, memory, ui, contracts, deployment" >&2; exit 2 ;; \
	esac

# Единый приемочный барьер для крупной или рискованной работы.
verify-full: check
	$(PYTHON) manage.py makemigrations --check --dry-run
	$(MAKE) contracts
	$(PYTEST) $(TEST_SCOPE) --migrations --reuse-db $(TEST_FLAGS)

contracts:
	$(PYTHON) manage.py validate_architecture_contracts

change-plan:
	$(PYTHON) manage.py generate_change_plan $(BRIEF) --output $(OUTPUT)

ai-runtime:
	uvicorn services.agent_runtime.app:app --host 0.0.0.0 --port 8090 --reload

gen-struct:
	node scripts/dev/generate-structure.js
