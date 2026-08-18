# Coding Agent Harness — one-click test / demo / install
# Windows: GNU make (mingw32-make) also works; POSIX: make
PYTHON ?= python

ifeq ($(OS),Windows_NT)
	SHELL := cmd.exe
	VENV_PY := .venv\Scripts\python.exe
else
	VENV_PY := .venv/bin/python
endif

.PHONY: test demo install

test: install
	$(VENV_PY) -m pytest harness/tests -q

demo: install
	$(VENV_PY) -m harness.tests.mechanism_demo.demo_1_guardrail_deny
	$(VENV_PY) -m harness.tests.mechanism_demo.demo_2_feedback_change
	$(VENV_PY) -m harness.tests.mechanism_demo.demo_3_hitl_trace

install:
	@$(PYTHON) -c "import pathlib,sys; sys.exit(0 if pathlib.Path(r'$(VENV_PY)').exists() else 1)" || $(PYTHON) -m venv .venv
	$(VENV_PY) -m pip install -e ".[dev]"
