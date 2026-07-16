PYTHON ?= python3

.PHONY: bootstrap-dev format lint typecheck test shellcheck check fake-ollama smoke-kali

bootstrap-dev:
	$(PYTHON) -m pip install -e ".[dev]"

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy src

test:
	$(PYTHON) -m pytest

shellcheck:
	bash -n scripts/*.sh
	bash -n shell/kali-copilot.bash
	@if command -v zsh >/dev/null 2>&1; then zsh -n shell/kali-copilot.zsh; else echo "zsh not installed; zsh syntax check skipped"; fi
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh shell/kali-copilot.bash; else echo "shellcheck not installed; bash syntax checks passed"; fi

check: lint typecheck test shellcheck

fake-ollama:
	$(PYTHON) -m tests.fake_ollama --host 127.0.0.1 --port 11435

smoke-kali:
	./scripts/smoke-kali.sh
