

# rag-livekit-agent-backend

> - livekit voice assistant agent backend
> - streaming tts audio to a2f
> - language input switch
  
  

### re-create this project
- prepare keys of: openai, deepgram, elevenlabs, livekit

- [Livekit CLI setup](https://docs.livekit.io/home/cli/cli-setup/) - Powershell - install livekit CLI
    - steps:
    ```bash
    # install Clivekit LI
    winget install LiveKit.LiveKitCLI
    # authenticate with cloud
    lk cloud auth
    ```

- [Create app from sample](https://docs.livekit.io/agents/quickstarts/voice-agent/) - Powershell - run cli to create app
    - steps:
    ```bash
    # cd to root folder
    cd [path]

    # cli create app (choose voice agent backend python)
    lk app create

    # create venev
    python -m venv venvname
    venvname/Scripts/Activate1.ps

    # use the requirements.txt in this repo
    pip install -r requirements.txt
    ```



