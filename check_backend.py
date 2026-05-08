import asyncio
import websockets
import json

async def test_stt():
    # Replace with your computer's IP address
    uri = "ws://192.168.2.4:8002"
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"Connected to {uri}")
            
            # Send dummy PCM bytes (16000 zero bytes as a test)
            dummy_audio = bytes([0] * 16000)
            await websocket.send(dummy_audio)
            print("Sent 16000 bytes of dummy audio...")
            
            # Wait for the response
            response = await websocket.recv()
            print(f"Received from server: {response}")
            
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_stt())