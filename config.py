import os
from dotenv import load_dotenv

load_dotenv()

# Bot Settings
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
BOT_NAME = "LARP | Assistance"

# Discord IDs
TICKET_CATEGORY_ID = 1509815613592436857
STAFF_ROLE_ID = 1508804635094286455
STAFF_PING_ID = 1508804635094286455
TICKETY_BOT_ID = 718493970652594217

# Timing
INITIAL_WAIT = 5
USER_RESPONSE_WAIT = 30

# AI System Prompt
SYSTEM_PROMPT = """You are a support assistant named "LARP | Assistance" for a Discord server.

Your rules:
- ALWAYS respond in English, no matter what language the user writes in
- Be warm, friendly and professional
- Keep responses concise and clear
- Help the user describe their issue if they are vague
- Do not make up information you don't have
- If you cannot solve the issue, let them know staff will assist them"""

SUMMARY_PROMPT = """Based on the support conversation below, write a short summary for the staff team.

Use ONLY English. Use this exact format:

**📋 Issue:** (one line description of the problem)

**📝 Details:** (2-3 key points from the conversation)

**⚡ Priority:** Low / Medium / High

Conversation:
{conversation}"""
