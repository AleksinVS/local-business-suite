PYTHON := ./.venv/bin/python

.PHONY: check test contracts change-plan

check:
	$(PYTHON) manage.py check

test:
	$(PYTHON) manage.py test

contracts:
	$(PYTHON) manage.py validate_architecture_contracts

change-plan:
	$(PYTHON) manage.py generate_change_plan $(BRIEF) --output $(OUTPUT)
