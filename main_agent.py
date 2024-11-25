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
import json

logger = logging.getLogger("rag-assistant")

# Load data
annoy_index = rag.annoy.AnnoyIndex.load("vdb_data")
load_dotenv(dotenv_path=".env.local")
embeddings_dimension = 1536
with open("data/data_1118_small.pkl", "rb") as f:
    paragraphs_by_uuid = pickle.load(f)

system_prompt_path = 'data/system_prompt.txt'
with open(system_prompt_path, 'r', encoding='utf-8') as file:
    system_prompt = file.read()


try:
    with(open("keys.json")) as fp:
        key_dict = json.load(fp)
except FileNotFoundError as e:
    key_dict = {}
grop_key = key_dict.get("grop")
model_id = key_dict.get("model_id")


class EntryDriver:
    def __init__(self):
        self.agent = None  # Initialize agent attribute
        self.ctx = None  # Store JobContext for potential reinitialization
        self.osc_server_running = False  # Flag to track OSC server status
        self.space_pressed = False  # 用于跟踪空格键是否被按下
    
    

    async def entrypoint(self, ctx: JobContext):
        # Store context to use in reset
        self.ctx = ctx

        initial_ctx = llm.ChatContext().append(
            role="system",
            text=(
                system_prompt
            ),
        )

        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        
        stop_strings = ["@"]

        async def process_and_accumulate_tts_source(tts_source: AsyncIterable[str]) -> AsyncIterable[str]:
            """
            處理 tts_source 的異步生成器，執行以下操作：
            1. 捕獲 "3. Response:" 後的內容。
            2. 在發現停止字符串時截斷。
            3. 累積並記錄所有內容。
            """
            capture = False  # 用於標記是否開始捕獲 "&&" 後的內容
            accumulated_text = ""  # 用於累積所有處理過的文本

            async for chunk in tts_source:
                # 累積捕獲到的內容
                accumulated_text += chunk
                #print(chunk)
                if not capture:
                    if "@" in chunk:
                        # 找到第一個 "@"，開始捕獲，保留其後的內容
                        capture = True
                        chunk = chunk.split("@", 1)[1]  # 提取 "@" 之後的部分
                    else:
                        # 如果未找到 "@"，跳過當前 chunk
                        continue

                # 如果捕獲已經開始，檢查是否遇到第二個 "@"
                if capture and "@" in chunk:
                    # 找到第二個 "@"，截斷到它之前並結束
                    chunk = chunk.split("@", 1)[0]
                    accumulated_text += chunk
                    yield chunk  # 返回最後一部分
                    break  # 停止捕獲

                
                yield chunk  # 將處理後的文本返回

            # 當所有內容處理完成後，一次性記錄累積的文本
            logger.info(f"TTS Input Accumulated and Processed Content: {accumulated_text}")

        def before_tts_cb(agent: "VoicePipelineAgent", tts_source: Union[str, AsyncIterable[str]]) -> Union[str, AsyncIterable[str]]:
            """
            綜合功能的回調函數：
            1. 當 tts_source 是字符串時，直接記錄並返回。
            2. 當 tts_source 是異步生成器時，進行處理和記錄。
            """
            if isinstance(tts_source, str):
                # 如果是字符串，記錄內容，無需處理，直接返回
                logger.info(f"TTS Input Content: {tts_source}")
                return tts_source

            # 如果是異步生成器，進行內容處理
            return process_and_accumulate_tts_source(tts_source)
    
        
        pre_txt = "Question: "
        post_txt = r"\n1. Topic categorization [#related or partially related or unrelated#]: \n2. Response tone [%happy or sad or confused or neutral%]: \n3. Response [@english@]:\n4. Translation of the response [*traditional chinese (zh-hk)*]: "

        async def _enrich_with_rag(agent: VoicePipelineAgent, chat_ctx: llm.ChatContext):
            stt_text = chat_ctx.messages[-1].content
            logger.info(f"Original STT text: {stt_text}")

            # RAG retrieval and context update logic
            user_msg = chat_ctx.messages[-1]
            user_msg_txt_for_embedding = chat_ctx.messages[-1].content.replace("you", "you (Friska)")
            user_msg_txt_for_embedding = user_msg_txt_for_embedding.replace("your", "your (Friska's)")
            user_embedding = await openai.create_embeddings(
                input=[user_msg_txt_for_embedding],
                model="text-embedding-3-small",
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
                #chat_ctx.messages[-1] = rag_msg
                #chat_ctx.messages.append(user_msg)

                modified_text = paragraph + "\n" + pre_txt + user_msg.content + post_txt
                chat_ctx.messages[-1].content = modified_text
                
                

            #logger.info(f"rag_msg: {rag_msg}")
            #logger.info(f"chat_ctx.messages[-1]: {chat_ctx.messages[-1]}")
            #return agent.llm.chat(chat_ctx=chat_ctx)
            
            


        

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
            stt=openai.STT.with_groq(language="yue", detect_language=False, api_key=grop_key), #only with grop cloud that can use large-v3 to use cantonese
            allow_interruptions = False,
            llm=openai.LLM(model=model_id),
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
      
        disp.map("/mand", self.on_mandarin)   
        disp.map("/can", self.on_cantonese)   
        disp.map("/en", self.on_english) 

        disp.map("/hold", self.on_hold_to_speak) 
        disp.map("/release", self.on_release) 

        # 設置 OSC 服務器
        server = osc_server.ThreadingOSCUDPServer(("127.0.0.1", 5566), disp)
        print("OSC Server is running on port 5566")
        server.serve_forever()
    
    def on_mandarin(self, address, *args):
        print("Received /mand OSC message!")
        logger.info("Received /mand OSC message!")
        # Run reset asynchronously
        if self.agent is not None and self.agent.stt is not None:
            self.agent.stt._stt._opts.language = "zh"  
            logger.info("self.agent.stt._opts.language = zh")
            print("self.agent.stt._opts.language = zh")
    
    def on_cantonese(self, address, *args):
        print("Received /can OSC message!")
        logger.info("Received /can OSC message!")
        # Run reset asynchronously
        if self.agent is not None and self.agent.stt is not None:
            self.agent.stt._stt._opts.language = "yue"  
            logger.info("self.agent.stt._opts.language = yue")
            print("self.agent.stt._opts.language = yue")

    def on_english(self, address, *args):
        print("Received /en OSC message!")
        logger.info("Received /en OSC message!")
        # Run reset asynchronously
        if self.agent is not None and self.agent.stt is not None:
            self.agent.stt._stt._opts.language = "en"  
            logger.info("self.agent.stt._opts.language = en")
            print("self.agent.stt._opts.language = en")

    def on_hold_to_speak(self, address, *args):
        
        print("Received /hold OSC message!")
        logger.info("Received /hold OSC message!")
        
        if self.agent is not None:
            self.agent.set_speakbtn_status(True)
            print("self.agent." + str(self.agent.is_speakbtn_hold))

    def on_release(self, address, *args):
      
        print("Received /release OSC message!")
        logger.info("Received /release OSC message!")
        
        if self.agent is not None:
            self.agent.set_speakbtn_status(False)
            print("self.agent." + str(self.agent.is_speakbtn_hold))

    def run(self):
       
        cli.run_app(WorkerOptions(entrypoint_fnc=self.entrypoint))


# Main program entry
if __name__ == "__main__":
    entry_driver = EntryDriver()
    entry_driver.run()

   