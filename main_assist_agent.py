import logging
import pickle
from dotenv import load_dotenv
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, rag, silero, elevenlabs

import tkinter as tk
import asyncio
from typing import Any, Union, AsyncIterable, Awaitable, Callable, Literal, Optional, Union

from pythonosc import dispatcher, osc_server, udp_client
import threading
import time
import json
import re
from livekit.plugins.openai.beta import (
    AssistantCreateOptions,
    AssistantLoadOptions,
    AssistantLLM,
    AssistantOptions,
    OnFileUploadedInfo,
)
logger = logging.getLogger("rag-assistant")

# Load data
annoy_index = rag.annoy.AnnoyIndex.load("vdb_data")
load_dotenv(dotenv_path=".env.local")
embeddings_dimension = 1536
with open("data/data_1118_large.pkl", "rb") as f:
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

        # 创建 OSC 客户端，目标地址为 localhost:5567
        self.osc_client = udp_client.SimpleUDPClient("127.0.0.1", 5567)
        self.osc_client_unity = udp_client.SimpleUDPClient("192.168.8.27", 5008)

        self.is_speakbtn_hold = False
    
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

        
        async def process_and_accumulate_tts_source(tts_source: AsyncIterable[str]) -> AsyncIterable[str]:
            buffer = ""  # 用于累积 chunk
            response_chi = ""
            response_eng = ""
            
            response_tone = None

            async for chunk in tts_source:
                if not chunk:
                    continue

                
                buffer += chunk

                
                # 检查是否能捕获 Response Tone
                if response_tone is None and "%" in buffer:
                    while True:
                        tone_match = re.search(r"%(.*?)%", buffer)
                        if tone_match:
                            response_tone = tone_match.group(1).strip()

                            # 检查是否包含 "tone"
                            if "tone" in response_tone.lower():
                                print(f"Skipped Tone containing 'tone': '{response_tone}'")
                                buffer = buffer.split("%", 2)[-1]
                                continue
                            else:
                                print(f"Valid Response Tone: {response_tone}")
                                self.osc_client_unity.send_message("/tone", str(response_tone))
                                logger.info(f"Tone sent to Unity: {response_tone}")
                                buffer = buffer.split("%", 2)[-1]
                                break
                        else:
                            break

                # 检查是否能捕获 Response English
                if response_tone and "@" in buffer:
                    response_eng_match = re.search(r"@(.*?)@", buffer, re.DOTALL)
                    if response_eng_match:
                        response_eng = response_eng_match.group(1).strip()
                        print(f"Response English: {response_eng}")
                        buffer = buffer.split("@", 2)[-1]

                        # Yield 逐块返回英文响应
                        for line in response_eng.splitlines():
                            yield line.strip()

                # 检查是否能捕获 Response Chinese
                if  response_tone and response_eng and "$" in buffer:
                    response_chi_match = re.search(r"\$(.*?)\$", buffer, re.DOTALL)
                    if response_chi_match:
                        response_chi = response_chi_match.group(1).strip()
                        print(f"Response Chinese: {response_chi}")
                        
                        # 发送 OSC 消息到 /response 地址
                        self.osc_client.send_message("/response", str(response_eng + "\n" + response_chi))
                        self.osc_client_unity.send_message("/response", str(response_chi))
                        buffer = buffer.split("$", 2)[-1]

            # 如果未捕获到 Response English，设置默认值
            if not response_eng:
                response_tone = "neutral"
                response_eng = "Friska not hear clear. Can you say again?"
                response_chi = "Friska沒有聽清，你可以再説一次嗎？"

                print(f"Tone={response_tone}, Response Eng={response_eng}, Response Chi={response_chi}")

                self.osc_client.send_message("/response", str(response_eng + "\n" + response_chi))
                self.osc_client_unity.send_message("/response", str(response_eng + "\n" + response_chi))
                self.osc_client_unity.send_message("/tone", "confused")
                
                response_eng = re.sub(r"[#@&￥]", "", response_eng)
                for line in response_eng.splitlines():
                    yield line.strip()

            # 打印缓冲区中剩余的未处理内容（如果有的话）
            if buffer.strip():
                print(f"Unprocessed Buffer: {buffer.strip()}")





        def before_tts_cb(agent: "VoicePipelineAgent", tts_source: Union[str, AsyncIterable[str]]) -> Union[str, AsyncIterable[str]]:
            if isinstance(tts_source, str):
                # 如果是字符串，記錄內容，無需處理，直接返回
                logger.info(f"TTS Input Content: {tts_source}")
                return tts_source

            # 如果是異步生成器，進行內容處理
            return process_and_accumulate_tts_source(tts_source)
    
        
        pre_txt = "User input: "
        post_txt = r"\n\n1. Topic categorization: #<categorization>#  \n2. Response tone: %<tone>% \n3. Response: @<response_in_english>@\n4. Translation of the response: $<translation_in_traditional chinese>$  "

        # async def _enrich_with_rag(agent: VoicePipelineAgent, chat_ctx: llm.ChatContext):
        #     stt_text = chat_ctx.messages[-1].content

        #     logger.info(f"Original STT text: {stt_text}")

        #     modified_stt_text = stt_text.replace("Hallo", "Hello")
        #     modified_stt_text = modified_stt_text.replace("Halo", "Hello")
        #     modified_stt_text = modified_stt_text.replace("halo", "hello")
        #     modified_stt_text = modified_stt_text.replace("HALOU", "Hello")
        #     modified_stt_text = modified_stt_text.replace("HALO", "Hello")
        #     modified_stt_text = modified_stt_text.replace("Halóo", "Hello")
        #     modified_stt_text = modified_stt_text.replace("Haló", "Hello")
        #     modified_stt_text = modified_stt_text.replace("haló", "hello")
        #     modified_stt_text = modified_stt_text.replace("Hai", "Hi")
        #     modified_stt_text = modified_stt_text.replace(" hai", " hi")
        #     modified_stt_text = modified_stt_text.replace("Fisca", "Friska")
        #     modified_stt_text = modified_stt_text.replace("Frisca", "Friska")
        #    # modified_stt_text = modified_stt_text.replace("Hmmm", "")
        #     #modified_stt_text = modified_stt_text.replace("hmmm", "")
        #    # modified_stt_text = modified_stt_text.replace("嗯", "")
        #     #modified_stt_text = modified_stt_text.replace("呵呵", "")
            

        #     # 发送 OSC 消息到 /chi 地址
        #     self.osc_client.send_message("/input", str(modified_stt_text).strip())
        #     self.osc_client_unity.send_message("/input", str(modified_stt_text).strip())

        #     # RAG retrieval and context update logic
        #     user_msg = chat_ctx.messages[-1]
        #     user_msg_txt_for_embedding = chat_ctx.messages[-1].content.replace("you", "you (Friska)")
        #     user_msg_txt_for_embedding = user_msg_txt_for_embedding.replace("your", "your (Friska's)")

        #     user_embedding = await openai.create_embeddings(
        #         input=[user_msg_txt_for_embedding],
        #         model="text-embedding-3-large",
        #         dimensions=embeddings_dimension,
        #     )
        #     result = annoy_index.query(user_embedding[0].embedding, n=1)[0]
        #     paragraph = paragraphs_by_uuid[result.userdata]
        #     if paragraph:
        #         logger.info(len(paragraph))
        #         logger.info(f"Enriching with RAG: {paragraph}")
                
        #         rag_msg = llm.ChatMessage.create(
        #             text="Context:\n" + paragraph,
        #             role="assistant",
        #         )
        #         #chat_ctx.messages[-1] = rag_msg
        #         #chat_ctx.messages.append(user_msg)

        #         modified_user_content = user_msg.content.replace("Hallo", "Hello")
        #         modified_user_content = modified_user_content.replace("HALOU", "Hello")
        #         modified_user_content = modified_user_content.replace("Halo", "Hello")
        #         modified_user_content = modified_user_content.replace("halo", "hello")
        #         modified_user_content = modified_user_content.replace("HALO", "Hello")
        #         modified_user_content = modified_user_content.replace("Halóo", "Hello")
        #         modified_user_content = modified_user_content.replace("Haló", "Hello")
        #         modified_user_content = modified_user_content.replace("haló", "hello")
        #         modified_user_content = modified_user_content.replace("Hai", "Hi")
        #         modified_user_content = modified_user_content.replace(" hai", " hi")
        #         modified_user_content = modified_user_content.replace("Fisca", "Friska")
        #         modified_user_content = modified_user_content.replace("Frisca", "Friska")
        #         #modified_user_content = modified_user_content.replace("Hmmm", "")
        #         #modified_user_content = modified_user_content.replace("hmmm", "")
        #         #modified_user_content = modified_user_content.replace("嗯", "")
        #         #modified_user_content = modified_user_content.replace("呵呵", "")
                
                
        #         print(len(user_msg_txt_for_embedding))
        #         if (len(user_msg_txt_for_embedding) < 10):
        #             paragraph = ""
        #         if (len(paragraph) < 50):
        #             paragraph = ""

        #         modified_text = "Context:" + paragraph + "\n\n" + pre_txt + modified_user_content + post_txt
        #         logger.info(modified_text)
        #         chat_ctx.messages[-1].content = modified_text

            #logger.info(f"rag_msg: {rag_msg}")
            #logger.info(f"chat_ctx.messages[-1]: {chat_ctx.messages[-1]}")
            #return agent.llm.chat(chat_ctx=chat_ctx)
        # pre_txt = "User input: "
        # post_txt = ""
        async def before_llm_cb(agent: VoicePipelineAgent, chat_ctx: llm.ChatContext) -> llm.LLMStream:
            # 获取 STT 转录的文本 (可以从 chat_ctx 中获取用户输入)
            stt_text = chat_ctx.messages[-1].content  # 假设最后一条消息是用户的输入

            stt_text = stt_text.replace("Hallo", "Hello")
            stt_text = stt_text.replace("HALOU", "Hello")
            stt_text = stt_text.replace("Halo", "Hello")
            stt_text = stt_text.replace("halo", "hello")
            stt_text = stt_text.replace("HALO", "Hello")
            stt_text = stt_text.replace("Halóo", "Hello")
            stt_text = stt_text.replace("Haló", "Hello")
            stt_text = stt_text.replace("haló", "hello")
            stt_text = stt_text.replace("Hai", "Hi")
            stt_text = stt_text.replace(" hai", " hi")
            stt_text = stt_text.replace("Fisca", "Friska")
            stt_text = stt_text.replace("Frisca", "Friska")
            stt_text = stt_text.replace("fuck", "??")
            stt_text = stt_text.replace("Fuck", "??")

                 # 发送 OSC 消息到 /chi 地址
            self.osc_client.send_message("/input", str(stt_text).strip())
            #self.osc_client_unity.send_message("/input", str(stt_text).strip())
         

            # 在这里修改 STT 输出的文本，例如替换敏感词等
            modified_text = pre_txt + stt_text + post_txt

            # 打印原始文本和修改后的文本，便于调试
            logger.info(f"Original STT text: {stt_text}")
            logger.info(f"Modified STT text: {modified_text}")

            # 更新 chat_ctx 的最后一条消息为修改后的文本
            # chat_ctx.messages[-1].content = modified_text

            # rag_msg = llm.ChatMessage.create(
            #         text="Context:\n" + paragraph,
            #         role="assistant",
            # )
            #     chat_ctx.messages[-1] = rag_msg
            #     chat_ctx.messages.append(user_msg)
            
            chat_ctx.messages[-1].content = modified_text

            # 返回默认的 LLMStream
            #return agent.llm.chat(chat_ctx=chat_ctx)
            

        # 创建 VoiceSettings 对象
        voice_settings = elevenlabs.VoiceSettings(
            stability=0.6, 
            similarity_boost=0.5, 
            style=0.2, 
            use_speaker_boost=True
        )

        # 创建 Voice 对象，设置 voice_id 和 voice_settings
        custom_voice = elevenlabs.Voice(
            id="yoUsTs4hf0a8NQ79GsEF", # #suci-u2b: "FZ8EqBA9DZ2GlefbqTYz", # suci: "JynqRycyCzSl9z1XWfvQ", # "0sTSlluslryPZcmMqZuZ", , # "lrHiVh9PuBpBiiTBXkHF", #"RlaD7H3pU627G2ZMcap7", #"5n8M7Ryj4WGvIblBxL83", # nagative "VkFD1gkULGl3924FMA5K",  # 替换为你的 voice_id
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
            llm=AssistantLLM(
            assistant_opts=AssistantOptions(
                load_options=AssistantLoadOptions(
                    assistant_id ="asst_A7IDaIjDKY69eWkGL4jPCdP3",
                    thread_id=None
                )
            )
        ),
            tts=elevenlabs.TTS(voice=custom_voice, encoding="pcm_24000"),
            before_llm_cb=before_llm_cb,
            before_tts_cb=before_tts_cb  # 传递自定义的 before_tts_cb 回调
        )

        # 订阅 user_stopped_speaking 事件
        self.agent.on("user_stopped_speaking", self.on_user_stopped_speaking)
        self.agent.on("agent_stopped_speaking", self.on_agent_stopped_speaking)
        self.agent.on("user_started_speaking", self.on_user_started_speaking)

        #self.agent.stt.is_mute = True  # Initialize as muted

        self.agent.start(ctx.room)
        await self.agent.say("Hi, me Friska.", allow_interruptions=True)

        # 讓 OSC 服務器在新的執行緒中運行
        # Start OSC server if not already running
        if not self.osc_server_running:
            self.osc_server_running = True  # Set flag to indicate server is running
            threading.Thread(target=self.start_osc_server, daemon=True).start()
        else:
            logger.info("OSC server is already running. Skipping startup.")

    def on_user_stopped_speaking(self):
            """Handle the user_stopped_speaking event and send OSC signal."""
            if self.is_speakbtn_hold == False:
                logger.info("User stopped speaking. Sending /endspeech OSC signal.")
                self.osc_client.send_message("/userstop", "User has stopped speaking")
    def on_agent_stopped_speaking(self):
            """Handle the user_stopped_speaking event and send OSC signal."""
            logger.info("User stopped speaking. Sending /endspeech OSC signal.")
            self.osc_client.send_message("/agentstop", "User has stopped speaking")
    def on_user_started_speaking(self):
        #send osc to unity to trigger listening animation
        self.osc_client_unity.send_message("/listen", [1])


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
            self.is_speakbtn_hold = True
            self.agent.set_speakbtn_status(True)
            print("self.agent." + str(self.agent.is_speakbtn_hold))

    def on_release(self, address, *args):
      
        print("Received /release OSC message!")
        logger.info("Received /release OSC message!")
        
        if self.agent is not None:
            self.is_speakbtn_hold = False
            self.agent.set_speakbtn_status(False)
            print("self.agent." + str(self.agent.is_speakbtn_hold))

    def run(self):
       
        cli.run_app(WorkerOptions(entrypoint_fnc=self.entrypoint))


# Main program entry
if __name__ == "__main__":
    entry_driver = EntryDriver()
    entry_driver.run()

   