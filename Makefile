PYTHON := ./.venv/bin/python
PYTHON_INSTALL := $(PYTHON) -m pip install

.PHONY: venv install check test test-all contracts change-plan ai-runtime gen-struct

venv:
	python3 -m venv .venv

install: venv
	$(PYTHON_INSTALL) -r requirements.txt

check:
	$(PYTHON) manage.py check

test:
	$(PYTHON) manage.py test

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
