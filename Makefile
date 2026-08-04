# Eva — companion robot
#   robot/   runs on the Raspberry Pi 4
#   server/  runs on the Mac mini
#
# Run `make` for the target list.

PY ?= python3

.PHONY: help setup-server models server test setup-robot robot mock dataset clean

SILERO_URL ?= https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx
SMART_TURN_URL ?= https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx

help:
	@echo "Mac mini (server):"
	@echo "  make setup-server   create server/.venv and install dependencies"
	@echo "  make models         download the voice activity and turn detection models"
	@echo "  make server         run the server on :8002 with autoreload"
	@echo "  make test           run the server test suite"
	@echo ""
	@echo "Raspberry Pi (robot):"
	@echo "  make setup-robot    create robot/.venv and install dependencies"
	@echo "  make robot          run the robot runtime"
	@echo ""
	@echo "Development:"
	@echo "  make mock           fake eva/1 server cycling movement commands"
	@echo "  make dataset        summarise captured training data"
	@echo "  make clean          remove venvs and __pycache__"

setup-server: models
	$(PY) -m venv server/.venv
	server/.venv/bin/pip install -q --upgrade pip
	server/.venv/bin/pip install -q -r server/requirements.txt
	@echo "Server ready. Start it with: make server"

# ~10 MB total. Kept out of git; without them the server still runs but
# treats every frame as speech and ends turns on silence alone.
models: server/models/silero_vad.onnx server/models/smart_turn.onnx

server/models/silero_vad.onnx:
	@mkdir -p server/models
	@echo "Fetching Silero VAD..."
	@curl -fsSL -o $@ $(SILERO_URL)

server/models/smart_turn.onnx:
	@mkdir -p server/models
	@echo "Fetching Smart Turn v3..."
	@curl -fsSL -o $@ $(SMART_TURN_URL)

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

dataset:
	cd server && .venv/bin/python tools/dataset_summary.py

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf robot/.venv server/.venv server/.pytest_cache
