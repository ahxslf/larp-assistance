import asyncio
from openai import AsyncOpenAI
from config import QWEN_API_KEY, SYSTEM_PROMPT, SUMMARY_PROMPT

client = AsyncOpenAI(
    api_key=QWEN_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

class AIHandler:
    def __init__(self):
        self.model = "llama3.3-70b-instruct"

    async def get_response(self, user_message: str, history: list[dict]) -> str:
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]

            for msg in history[:-1]:  # son mesajı (user_message) zaten alta ekliyoruz
                messages.append({
                    "role": msg["role"] if msg["role"] != "assistant" else "assistant",
                    "content": msg["content"]
                })

            messages.append({"role": "user", "content": user_message})

            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"[AI Error] {e}")
            return (
                "I'm having trouble processing your request right now. "
                "A staff member will assist you shortly."
            )

    async def generate_summary(self, conversation: list[dict]) -> str:
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in conversation
            ])

            prompt = SUMMARY_PROMPT.format(conversation=conversation_text)

            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )
            return response.choices[0].message.content

        except Exception as e:
            print(f"[Summary Error] {e}")
            return "**📋 Summary could not be generated automatically.**"
