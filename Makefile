PYTHON ?= python3

.PHONY: install check build

install:
	$(PYTHON) -m pip install -e '.[dev]'

check:
	$(PYTHON) scripts/check.py

build:
	$(PYTHON) -m build
