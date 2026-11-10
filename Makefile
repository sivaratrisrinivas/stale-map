PY ?= .venv/bin/python

.PHONY: test check site all
test:
	$(PY) -m pytest -q

# Rescore everything from the shipped slim data. No network.
check:
	$(PY) -m stale_map.analyze
	$(PY) site/build.py

site: check

all: test check
