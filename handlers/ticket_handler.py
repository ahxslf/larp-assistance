import asyncio
import discord
from config import (
    INITIAL_WAIT, USER_RESPONSE_WAIT,
    STAFF_PING_ID, BOT_NAME
)
from handlers.ai_handler import AIHandler

ai = AIHandler()

active_tickets: dict[int, dict] = {}

def extract_username(channel_name: str) -> str:
    parts = channel_name.split("-", 1)
    return parts[1] if len(parts) > 1 else channel_name

def find_member_by_username(guild: discord.Guild, username: str) -> discord.Member | None:
    username_lower = username.lower()
    for member in guild.members:
        if member.display_name.lower() == username_lower:
            return member
        if member.name.lower() == username_lower:
            return member
        if member.nick and member.nick.lower() == username_lower:
            return member
    return None

async def handle_new_ticket(bot, channel: discord.TextChannel, guild: discord.Guild):
    channel_id = channel.id
    username = extract_username(channel.name)

    active_tickets[channel_id] = {
        "stopped": False,
        "waiting": False,
        "first_message_done": False,
        "conversation": [],
        "summary_msg": None,
        "user": None,
    }

    print(f"[Ticket] New ticket: #{channel.name} | Username: {username}")

    await asyncio.sleep(INITIAL_WAIT)

    if active_tickets[channel_id]["stopped"]:
        return

    member = find_member_by_username(guild, username)
    active_tickets[channel_id]["user"] = member

    if member:
        ping_text = member.mention
    else:
        ping_text = f"**{username}**"

    await channel.send(
        f"{ping_text} 👋 Hello! I'm **{BOT_NAME}**, your automated support assistant.\n\n"
        f"Please describe your issue and I'll do my best to help you right away!\n"
        f"*(You have **{USER_RESPONSE_WAIT} seconds** to send your first message. "
        f"If you need more time, don't worry — I'll wait for you!)*"
    )

    def check(m: discord.Message) -> bool:
        if active_tickets.get(channel_id, {}).get("stopped"):
            return False
        if m.author.bot:
            return False
        if m.channel.id != channel_id:
            return False
        if member:
            return m.author.id == member.id
        return True

    first_msg = None

    try:
        first_msg = await bot.wait_for(
            "message", check=check, timeout=USER_RESPONSE_WAIT
        )

    except asyncio.TimeoutError:
        if active_tickets[channel_id]["stopped"]:
            return

        active_tickets[channel_id]["waiting"] = True

        await channel.send(
            f"⏳ **{BOT_NAME}:** No worries, take your time! "
            f"I'm still here whenever you're ready."
        )

        try:
            first_msg = await bot.wait_for(
                "message", check=check, timeout=None
            )
        except Exception as e:
            print(f"[Ticket] Wait mode error: {e}")
            return

    if not first_msg or active_tickets[channel_id]["stopped"]:
        return

    active_tickets[channel_id]["waiting"] = False

    active_tickets[channel_id]["conversation"].append({
        "role": "user",
        "content": first_msg.content
    })

    async with channel.typing():
        ai_response = await ai.get_response(
            first_msg.content,
            active_tickets[channel_id]["conversation"]
        )

    await channel.send(f"**{BOT_NAME}:** {ai_response}")

    active_tickets[channel_id]["conversation"].append({
        "role": "assistant",
        "content": ai_response
    })

    active_tickets[channel_id]["first_message_done"] = True
    print(f"[Ticket] First exchange done in #{channel.name}")
    # ⬆️ Summary burada YOK — kullanıcı daha fazla bilgi vermeden summary yapılmaz

async def send_summary(
    channel: discord.TextChannel,
    guild: discord.Guild,
    channel_id: int,
    version: int = 1
):
    if active_tickets[channel_id]["stopped"]:
        return

    conversation = active_tickets[channel_id]["conversation"]
    summary_text = await ai.generate_summary(conversation)

    staff_role = guild.get_role(STAFF_PING_ID)
    staff_mention = staff_role.mention if staff_role else "@Staff"

    full_message = (
        f"{'━' * 35}\n"
        f"📊 **TICKET SUMMARY v{version}** — {staff_mention}\n"
        f"{'━' * 35}\n"
        f"{summary_text}\n"
        f"{'━' * 35}"
    )

    existing_summary = active_tickets[channel_id]["summary_msg"]

    if existing_summary is None:
        summary_msg = await channel.send(full_message)
        active_tickets[channel_id]["summary_msg"] = summary_msg
    else:
        try:
            await existing_summary.edit(content=full_message)
        except discord.NotFound:
            summary_msg = await channel.send(full_message)
            active_tickets[channel_id]["summary_msg"] = summary_msg

async def handle_followup_message(message: discord.Message, guild: discord.Guild):
    channel_id = message.channel.id
    ticket = active_tickets.get(channel_id)

    if not ticket:
        return
    if ticket["stopped"]:
        return
    if message.author.bot:
        return

    user = ticket.get("user")
    if user and message.author.id != user.id:
        return

    ticket["conversation"].append({
        "role": "user",
        "content": message.content
    })

    async with message.channel.typing():
        ai_response = await ai.get_response(
            message.content,
            ticket["conversation"]
        )

    await message.channel.send(f"**{BOT_NAME}:** {ai_response}")

    ticket["conversation"].append({
        "role": "assistant",
        "content": ai_response
    })

    user_message_count = len(
        [m for m in ticket["conversation"] if m["role"] == "user"]
    )

    # ✅ Summary: kullanıcı en az 2 mesaj gönderdikten sonra başla, sonra her mesajda güncelle
    if user_message_count >= 2:
        await send_summary(message.channel, guild, channel_id, version=user_message_count)

def stop_ticket(channel_id: int) -> bool:
    if channel_id in active_tickets:
        active_tickets[channel_id]["stopped"] = True
        return True
    return False

def is_active_ticket(channel_id: int) -> bool:
    return channel_id in active_tickets and not active_tickets[channel_id]["stopped"]

def is_first_message_done(channel_id: int) -> bool:
    ticket = active_tickets.get(channel_id)
    if not ticket:
        return False
    return ticket.get("first_message_done", False)
