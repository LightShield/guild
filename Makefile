PYTHON ?= python3.11
PIP ?= pip3.11
GUILD ?= guild
PROVIDER ?= codex
MODEL ?= $(PROVIDER)
TASK ?= Create a hello.txt file containing 'Hello from Guild'
HOST ?= 127.0.0.1
PORT ?= 8585
UI_HOST ?= 127.0.0.1
UI_PORT ?= 5173

.DEFAULT_GOAL := help

.PHONY: help install install-api install-dev ui-install ui-build init install-mixed-team start dev dev-api dev-ui terminate-all-agents config config-claude config-codex task task-claude task-codex team-codex-claude chat test test-unit lint format typecheck check clean

help:
	@printf '%s\n' 'Guild development shortcuts'
	@printf '%s\n' ''
	@printf '%s\n' 'Setup:'
	@printf '%s\n' '  make install        Install package locally'
	@printf '%s\n' '  make install-api    Install package with API server dependencies'
	@printf '%s\n' '  make install-dev    Install package with dev dependencies'
	@printf '%s\n' '  make ui-install     Install UI dependencies'
	@printf '%s\n' '  make ui-build       Build bundled UI'
	@printf '%s\n' '  make init           Initialize .guild/'
	@printf '%s\n' '  make install-mixed-team'
	@printf '%s\n' '  make start          Build UI, install mixed team, start API/UI'
	@printf '%s\n' '  make dev            Start hot-reload API + UI'
	@printf '%s\n' '  make dev-api        Start API with reload'
	@printf '%s\n' '  make dev-ui         Start Vite UI with HMR'
	@printf '%s\n' '  make terminate-all-agents'
	@printf '%s\n' ''
	@printf '%s\n' 'Claude/Codex usage:'
	@printf '%s\n' '  make task-codex TASK="..."'
	@printf '%s\n' '  make task-claude TASK="..."'
	@printf '%s\n' '  make team-codex-claude TASK="..."'
	@printf '%s\n' '  make chat'
	@printf '%s\n' ''
	@printf '%s\n' 'Checks:'
	@printf '%s\n' '  make test-unit'
	@printf '%s\n' '  make check'

install:
	$(PIP) install -e .

install-api:
	$(PIP) install -e ".[api]"

install-dev:
	$(PIP) install -e ".[dev]"

ui-install:
	npm --prefix ui ci

ui-build: ui-install
	npm --prefix ui run build

init:
	$(GUILD) init

install-mixed-team: init
	mkdir -p .guild/blocks
	cp examples/blocks/planner_codex.toml .guild/blocks/
	cp examples/blocks/coder_codex.toml .guild/blocks/
	cp examples/blocks/reviewer_claude.toml .guild/blocks/
	cp examples/blocks/team_codex_claude.toml .guild/blocks/

start: install-api ui-build install-mixed-team
	$(GUILD) serve --host $(HOST) --port $(PORT)

dev: install-api ui-install install-mixed-team
	@printf '%s\n' 'API: http://$(HOST):$(PORT)'
	@printf '%s\n' 'UI:  http://$(UI_HOST):$(UI_PORT)'
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory dev-api & \
	$(MAKE) --no-print-directory dev-ui & \
	wait

dev-api:
	$(PYTHON) -m uvicorn 'guild.api.server:create_app' --factory --reload --host $(HOST) --port $(PORT)

dev-ui:
	npm --prefix ui run dev -- --host $(UI_HOST) --port $(UI_PORT)

terminate-all-agents:
	-@pkill -TERM -f 'guild\.daemon\.(run|team_run)|codex exec|claude .*--dangerously-skip-permissions|claude --dangerously-skip-permissions|claude .* -p ' 2>/dev/null || true
	-@sleep 1
	-@pkill -KILL -f 'guild\.daemon\.(run|team_run)|codex exec|claude .*--dangerously-skip-permissions|claude --dangerously-skip-permissions|claude .* -p ' 2>/dev/null || true
	@printf '%s\n' 'Requested termination for Guild daemon agents and Codex/Claude child CLI runs.'

config:
	$(GUILD) config --set provider.provider_name=$(PROVIDER)
	$(GUILD) config --set provider.model=$(MODEL)

config-claude:
	$(MAKE) config PROVIDER=claude MODEL=claude

config-codex:
	$(MAKE) config PROVIDER=codex MODEL=codex

task:
	$(GUILD) task "$(TASK)"

task-claude:
	GUILD_PROVIDER_NAME=claude GUILD_MODEL=claude $(GUILD) task "$(TASK)"

task-codex:
	GUILD_PROVIDER_NAME=codex GUILD_MODEL=codex $(GUILD) task "$(TASK)"

team-codex-claude: install-mixed-team
	$(GUILD) team --team codex-claude "$(TASK)"

chat:
	$(GUILD) chat

test:
	$(PYTHON) -m pytest

test-unit:
	$(PYTHON) -m pytest -m unit

lint:
	ruff check src/ tests/

format:
	black src/ tests/

typecheck:
	mypy src/guild/ --strict

check: lint typecheck test-unit

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
