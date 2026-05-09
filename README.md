# STT API Server

This folder contains a simple Flask-based API to receive audio from the robot and return transcribed text.

## How to use on your local computer:

1. **Move this folder** to your computer.
2. **Create a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the server**:
   ```bash
   python app.py
   ```
5. **Update Robot Config**:
   On your robot, update the `SpeechAPIConfig` in `config.py` to point to your computer's IP address:
   ```python
   # Example:
   base_url: str = "http://192.168.1.50:8002" 
   ```

## Note on Transcription
The current `app.py` is a **stub**. It returns "hello robot" for every audio chunk. To make it real, you should integrate a library like `openai-whisper` or `vosk` inside the `transcribe()` function in `app.py`.
