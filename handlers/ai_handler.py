from openai import AsyncOpenAI
from config import GROQ_API_KEY, SYSTEM_PROMPT, SUMMARY_PROMPT

client = AsyncOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

class AIHandler:
    def __init__(self):
        self.model = "llama-3.3-70b-versatile"

    async def get_response(self, user_message: str, history: list[dict]) -> str:
        try:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            for msg in history[:-1]:
                messages.append({"role": msg["role"], "content": msg["content"]})
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

    async def generate_summary(self, conversation: list[dict]) -> tuple[bool, str]:
        """
        Returns (escalate, summary_text).

        escalate -> whether the staff team should be pinged / a summary posted.
        summary_text -> the cleaned summary body (without the ESCALATE line).

        On error we default to escalate=True so important tickets are never
        silently dropped.
        """
        try:
            conversation_text = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in conversation
            ])
            prompt = SUMMARY_PROMPT.format(conversation=conversation_text)

            response = await client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content or ""

            return self._parse_summary(raw)

        except Exception as e:
            print(f"[Summary Error] {e}")
            return True, "**📋 Summary could not be generated automatically.**"

    @staticmethod
    def _parse_summary(raw: str) -> tuple[bool, str]:
        """Pull the ESCALATE decision off the top and return the rest as body."""
        escalate = True  # safe default
        body_lines: list[str] = []

        for line in raw.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("ESCALATE:"):
                decision = upper.split(":", 1)[1].strip()
                escalate = not decision.startswith("NO")
                continue
            body_lines.append(line)

        body = "\n".join(body_lines).strip()
        if not body:
            body = "**📋 Summary could not be generated automatically.**"
        return escalate, body
