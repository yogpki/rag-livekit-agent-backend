# rag-livekit-agent-backend

> **⚠️ This project is a work in progress.**  
> - livekit voice assistant agent backend  
> - streaming tts audio to a2f  
> - language input switch  

---

### Re-create this project

1. **Prepare API keys**  
   OpenAI, Deepgram, ElevenLabs, and LiveKit.

2. **Prepare Nvidia omniverse - audio2face**
    - [Install Omniverse launcher](https://developer.nvidia.com/omniverse#section-getting-started)
    - Install audio2face in the launcher
    - [u2b - Setup the scene w/ blendshape osc](https://www.youtube.com/watch?v=y1wVykdmJNM)
        ```bash
          #shapes in \AppData\Local\ov\pkg\audio2face-2023.2.0\exts\omni.audio2face.exporter\omni\audio2face\exporter\scripts\faceSolerv.py
          blend = ["eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft", "eyeSquintLeft", "eyeWideLeft", "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight", "eyeSquintRight", "eyeWideRight", "jawForward", "jawLeft", "jawRight", "jawOpen", "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight", "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight", "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight", "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthUpperUpLeft", "mouthUpperUpRight", "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight", "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "noseSneerLeft", "noseSneerRight", "tongueOut"]
        ```
            
3. **[Livekit CLI setup](https://docs.livekit.io/home/cli/cli-setup/)**  
   Use Powershell to install the LiveKit CLI:
   
   - Steps:
     ```bash
     # Install LiveKit CLI
     winget install LiveKit.LiveKitCLI

     # Authenticate with cloud
     lk cloud auth
     ```

4. **[Create app from livekit sample](https://docs.livekit.io/agents/quickstarts/voice-agent/)**  
   Use Powershell to run the CLI and create the app:

   - Steps:
     ```bash
     # Navigate to the root folder
     cd [path]

     # Use CLI to create app (select voice agent backend in Python)
     lk app create

     # Create a virtual environment
     python -m venv venvname
     venvname/Scripts/Activate.ps1

     # Install dependencies from requirements.txt in this repo
     pip install -r requirements.txt
     ```

### Notes
- Capturing audio data from the voice agent and streaming them to a2f at 
    `simpleenv\Lib\site-packages\livekit\agents\pipeline\agent_playout.py`
- Currently the original audio playout is deleted. So it is a must to run the a2f streaming usd file since the streaming needs a destination.

### Code reference
- a2f streaming function reference at `\AppData\Local\ov\pkg\audio2face-2023.2.0\exts\omni.audio2face.player\omni\audio2face\player\scripts\streaming_server\test_client.py`. Use it and modify the push_audio_track_stream function at agent_playout.py, so that it can send the start_market at first frame and send the rest audio to a2f.