import asyncio
import google.generativeai as genai
from config import GEMINI_API_KEY, SYSTEM_PROMPT, SUMMARY_PROMPT

genai.configure(api_key=GEMINI_API_KEY)

class AIHandler:
    def __init__(self):
        self.model = genai.GenerativeModel("gemini-2.5-flash")

    async def get_response(self, user_message: str, history: list[dict]) -> str:
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in history
            ])

            prompt = f"""{SYSTEM_PROMPT}

Conversation so far:
{conversation_text}

User: {user_message}
