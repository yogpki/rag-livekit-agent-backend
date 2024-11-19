import logging
import pickle
from dotenv import load_dotenv
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, rag, silero,elevenlabs

from typing import Any, Union, AsyncIterable, Awaitable, Callable, Literal, Optional, Union



logger = logging.getLogger("rag-assistant")
annoy_index = rag.annoy.AnnoyIndex.load("vdb_data")  # see build_data.py
load_dotenv(dotenv_path=".env.local")
embeddings_dimension = 1536 #1536
with open("data/data_1118.pkl", "rb") as f:
    paragraphs_by_uuid = pickle.load(f)

    # Specify the path to your text file
file_path = 'data/system_prompt.txt'
#file_path = 'data/andy_system_1.txt'
#file_path = 'data/andy_system_2.txt'
#file_path = 'data/andy_system_3.txt'
#file_path = 'data/andy_system_4.txt'
#file_path = 'data/andy_system_5.txt'

# Open the file in read mode and read the content into a string
with open(file_path, 'r', encoding='utf-8') as file:
    system_prompt = file.read()



async def entrypoint(ctx: JobContext):
    # 创建 VoiceSettings 对象
    voice_settings = elevenlabs.VoiceSettings(
        stability=0.8, 
        similarity_boost=0.5, 
        style=0.6, 
        use_speaker_boost=True
    )

    # 创建 Voice 对象，设置 voice_id 和 voice_settings
    custom_voice = elevenlabs.Voice(
        id= "RlaD7H3pU627G2ZMcap7", #"5n8M7Ryj4WGvIblBxL83", # nagative "VkFD1gkULGl3924FMA5K",  # 替换为你的 voice_id
        name="Sad Voice",
        category="general",
        settings=voice_settings
    )

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
        # locate the last user message and use it to query the RAG model
        # to get the most relevant paragraph
        # then provide that as additional context to the LLM
        user_msg = chat_ctx.messages[-1]
        user_embedding = await openai.create_embeddings(
            input=[user_msg.content],
            model="text-embedding-3-large",
            dimensions=embeddings_dimension,
        )

        result = annoy_index.query(user_embedding[0].embedding, n=1)[0]
        paragraph = paragraphs_by_uuid[result.userdata]
        if paragraph:
            logger.info(f"enriching with RAG: {paragraph}")
            rag_msg = llm.ChatMessage.create(
                text="Context:\n" + paragraph,
                role="assistant",
            )
            # replace last message with RAG, and append user message at the end
            chat_ctx.messages[-1] = rag_msg
            chat_ctx.messages.append(user_msg)



    initial_ctx = llm.ChatContext().append(
        role="system",
        text=(
             system_prompt
        ),
    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    agent = VoicePipelineAgent(
        chat_ctx=initial_ctx,
        vad=silero.VAD.load(),
        stt=openai.STT(
            language="en",           # 可选，设置为 `None` 以启用自动检测
            detect_language=False     # 启用语言检测 # streamming 不能用detect
        ),

        llm=openai.LLM(),
        allow_interruptions=False,
        tts=elevenlabs.TTS(voice=custom_voice,
                            encoding="pcm_24000" ), # 設置為 PCM 格式
        before_llm_cb=_enrich_with_rag,
        before_tts_cb=before_tts_cb  # 传递自定义的 before_tts_cb 回调
    )

    agent.start(ctx.room)

    await agent.say("Hey, testing with friska?", allow_interruptions=True)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))