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

            prompt = (
                f"{SYSTEM_PROMPT}\n\n"
                f"Conversation so far:\n{conversation_text}\n\n"
                f"User: {user_message}\n\n"
                f"Assistant:"
            )

            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text

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

            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text

        except Exception as e:
            print(f"[Summary Error] {e}")
            return "**📋 Summary could not be generated automatically.**"
