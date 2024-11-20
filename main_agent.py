import logging
import pickle
from dotenv import load_dotenv
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, rag, silero, elevenlabs

import tkinter as tk
import asyncio
from typing import Any, Union, AsyncIterable, Awaitable, Callable, Literal, Optional, Union

from pythonosc import dispatcher, osc_server
import threading
import time

logger = logging.getLogger("rag-assistant")

# Load data
annoy_index = rag.annoy.AnnoyIndex.load("vdb_data")
load_dotenv(dotenv_path=".env.local")
embeddings_dimension = 1536
with open("data/data_1118.pkl", "rb") as f:
    paragraphs_by_uuid = pickle.load(f)

system_prompt_path = 'data/system_prompt.txt'
with open(system_prompt_path, 'r', encoding='utf-8') as file:
    system_prompt = file.read()

class EntryDriver:
    def __init__(self):
        self.agent = None  # Initialize agent attribute
        self.ctx = None  # Store JobContext for potential reinitialization
        self.osc_server_running = False  # Flag to track OSC server status

    async def entrypoint(self, ctx: JobContext):
        # Store context to use in reset
        self.ctx = ctx

        

        def before_tts_cb(agent: VoicePipelineAgent, tts_source: Union[str, AsyncIterable[str]]) -> Union[str, AsyncIterable[str]]:
            # 檢查 tts_source 是否為字符串
            if isinstance(tts_source, str):
                logger.info(f"TTS Input Content: {tts_source}")
                return tts_source

            # 當 tts_source 是異步生成器時，累積內容並一次性打印
            async def accumulate_and_print_source(source: AsyncIterable[str]) -> AsyncIterable[str]:
                accumulated_text = ""
                async for text in source:
                    accumulated_text += text  # 累積文本
                    yield text  # 繼續生成 tts_source 的內容
                # 當所有文本累積完成後一次性打印
                logger.info(f"TTS Input Accumulated Content: {accumulated_text}")

            return accumulate_and_print_source(tts_source)
    
        async def _enrich_with_rag(agent: VoicePipelineAgent, chat_ctx: llm.ChatContext):
            stt_text = chat_ctx.messages[-1].content
            logger.info(f"Original STT text: {stt_text}")

            # RAG retrieval and context update logic
            user_msg = chat_ctx.messages[-1]
            user_embedding = await openai.create_embeddings(
                input=[user_msg.content],
                model="text-embedding-3-large",
                dimensions=embeddings_dimension,
            )
            result = annoy_index.query(user_embedding[0].embedding, n=1)[0]
            paragraph = paragraphs_by_uuid[result.userdata]
            if paragraph:
                logger.info(f"Enriching with RAG: {paragraph}")
                rag_msg = llm.ChatMessage.create(
                    text="Context:\n" + paragraph,
                    role="assistant",
                )
                chat_ctx.messages[-1] = rag_msg
                chat_ctx.messages.append(user_msg)

        initial_ctx = llm.ChatContext().append(
            role="system",
            text=(
                system_prompt
            ),
        )

        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        # 创建 VoiceSettings 对象
        voice_settings = elevenlabs.VoiceSettings(
            stability=0.4, 
            similarity_boost=0.5, 
            style=0.2, 
            use_speaker_boost=True
        )

        # 创建 Voice 对象，设置 voice_id 和 voice_settings
        custom_voice = elevenlabs.Voice(
            id= "RlaD7H3pU627G2ZMcap7", #"5n8M7Ryj4WGvIblBxL83", # nagative "VkFD1gkULGl3924FMA5K",  # 替换为你的 voice_id
            name="Sad Voice",
            category="general",
            settings=voice_settings
        )

        # Create VoicePipelineAgent and assign it to self.agent
        self.agent = VoicePipelineAgent(
            chat_ctx=initial_ctx,
            vad=silero.VAD.load(),
            stt=openai.STT(language="en", detect_language=False),
            allow_interruptions = False,
            llm=openai.LLM(),
            tts=elevenlabs.TTS(voice=custom_voice, encoding="pcm_24000"),
            before_llm_cb=_enrich_with_rag,
            before_tts_cb=before_tts_cb  # 传递自定义的 before_tts_cb 回调
        )

        #self.agent.stt.is_mute = True  # Initialize as muted

        self.agent.start(ctx.room)
        await self.agent.say("Hey, language test today?", allow_interruptions=True)

        # 讓 OSC 服務器在新的執行緒中運行
        # Start OSC server if not already running
        if not self.osc_server_running:
            self.osc_server_running = True  # Set flag to indicate server is running
            threading.Thread(target=self.start_osc_server, daemon=True).start()
        else:
            logger.info("OSC server is already running. Skipping startup.")

       
    def start_osc_server(self):
        # 配置 OSC 分派器
        disp = dispatcher.Dispatcher()
      
        disp.map("/mand", self.on_chinese)   
        disp.map("/can", self.on_chinese)   
        disp.map("/en", self.on_english) 

        # 設置 OSC 服務器
        server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 5566), disp)
        print("OSC Server is running on port 5566")
        server.serve_forever()
    
    def on_chinese(self, address, *args):
        """Trigger reset when receiving /mand or /can OSC message."""
        print("Received /mand or /can OSC message!")
        logger.info("Received /mand or /can OSC message!")
        # Run reset asynchronously
        if self.agent is not None and self.agent.stt is not None:
            self.agent.stt._stt._opts.language = "zh"  
            logger.info("self.agent.stt._opts.language = zh")
            print("self.agent.stt._opts.language = zh")

    def on_english(self, address, *args):
        """Trigger reset when receiving /en OSC message."""
        print("Received /en OSC message!")
        logger.info("Received /en OSC message!")
        # Run reset asynchronously
        if self.agent is not None and self.agent.stt is not None:
            self.agent.stt._stt._opts.language = "en"  
            logger.info("self.agent.stt._opts.language = en")
            print("self.agent.stt._opts.language = en")


    def run(self):
        cli.run_app(WorkerOptions(entrypoint_fnc=self.entrypoint))


# Main program entry
if __name__ == "__main__":
    entry_driver = EntryDriver()
    entry_driver.run()

