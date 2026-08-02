# Eva — companion robot
#   robot/   runs on the Raspberry Pi 4
#   server/  runs on the Mac mini
#
# Run `make` for the target list.

PY ?= python3

.PHONY: help setup-server server test setup-robot robot mock clean

help:
	@echo "Mac mini (server):"
	@echo "  make setup-server   create server/.venv and install dependencies"
	@echo "  make server         run the server on :8002 with autoreload"
	@echo "  make test           run the server test suite"
	@echo ""
	@echo "Raspberry Pi (robot):"
	@echo "  make setup-robot    create robot/.venv and install dependencies"
	@echo "  make robot          run the robot runtime"
	@echo ""
	@echo "Development:"
	@echo "  make mock           fake server cycling movement commands (no Mac needed)"
	@echo "  make clean          remove venvs and __pycache__"

setup-server:
	$(PY) -m venv server/.venv
	server/.venv/bin/pip install -q --upgrade pip
	server/.venv/bin/pip install -q -r server/requirements.txt
	@echo "Server ready. Start it with: make server"

server:
	cd server && .venv/bin/uvicorn asgi:app --host 0.0.0.0 --port 8002 --reload

test:
	cd server && .venv/bin/python -m pytest -q

setup-robot:
	$(PY) -m venv robot/.venv
	robot/.venv/bin/pip install -q --upgrade pip
	robot/.venv/bin/pip install -q -r robot/requirements.txt
	@echo "Robot ready. Start it with: make robot"

robot:
	cd robot && .venv/bin/python main.py

mock:
	cd server && .venv/bin/python tools/mock_command_server.py

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf robot/.venv server/.venv server/.pytest_cache
