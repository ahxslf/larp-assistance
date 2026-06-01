import google.generativeai as genai
from config import GEMINI_API_KEY, SYSTEM_PROMPT, SUMMARY_PROMPT

genai.configure(api_key=GEMINI_API_KEY)


class AIHandler:
    def __init__(self):
        # ✅ Model güncellendi: gemini-2.0-flash-exp (en yeni ücretsiz model)
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp")

    async def get_response(self, user_message: str, history: list[dict]) -> str:
        """Generate AI response to user message"""
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in history
            ])

            prompt = f"""{SYSTEM_PROMPT}

Conversation so far:
{conversation_text}

User: {user_message}
Assistant:"""

            response = self.model.generate_content(prompt)
            return response.text

        except Exception as e:
            print(f"[AI Error] {e}")
            return (
                "I'm having trouble processing your request right now. "
                "A staff member will assist you shortly."
            )

    async def generate_summary(self, conversation: list[dict]) -> str:
        """Generate a summary from the conversation"""
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in conversation
            ])

            prompt = SUMMARY_PROMPT.format(conversation=conversation_text)
            response = self.model.generate_content(prompt)
            return response.text

        except Exception as e:
            print(f"[Summary Error] {e}")
            return "**📋 Summary could not be generated automatically.**"
