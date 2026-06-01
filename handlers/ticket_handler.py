import asyncio
import discord
from config import (
    INITIAL_WAIT, USER_RESPONSE_WAIT,
    STAFF_PING_ID, BOT_NAME
)
from handlers.ai_handler import AIHandler

ai = AIHandler()

# { channel_id: { "stopped": bool, "waiting": bool, "conversation": [], "summary_msg": Message, "user": Member } }
active_tickets: dict[int, dict] = {}


def extract_username(channel_name: str) -> str:
    """'support-username' -> 'username'"""
    parts = channel_name.split("-", 1)
    return parts[1] if len(parts) > 1 else channel_name


def find_member_by_username(guild: discord.Guild, username: str) -> discord.Member | None:
    """Find a member by display name, global name or nickname"""
    username_lower = username.lower()

    for member in guild.members:
        if member.display_name.lower() == username_lower:
            return member
        if member.name.lower() == username_lower:
            return member
        if member.nick and member.nick.lower() == username_lower:
            return member

    return None


async def handle_new_ticket(channel: discord.TextChannel, guild: discord.Guild):
    """Runs when a new ticket channel is created"""

    channel_id = channel.id
    username = extract_username(channel.name)

    # Register ticket
    active_tickets[channel_id] = {
        "stopped": False,
        "waiting": False,
        "conversation": [],
        "summary_msg": None,
        "user": None,
    }

    print(f"[Ticket] New ticket: #{channel.name} | Extracted username: {username}")

    # Wait 5 seconds
    await asyncio.sleep(INITIAL_WAIT)

    if active_tickets[channel_id]["stopped"]:
        return

    # Find member from channel name
    member = find_member_by_username(guild, username)
    active_tickets[channel_id]["user"] = member

    if member:
        print(f"[Ticket] Matched member: {member} (ID: {member.id})")
        ping_text = member.mention
    else:
        print(f"[Ticket] No member found for username: '{username}', sending without ping")
        ping_text = f"**{username}**"

    # Send opening message
    await channel.send(
        f"{ping_text} 👋 Hello! I'm **{BOT_NAME}**, your automated support assistant.\n\n"
        f"Please describe your issue and I'll do my best to help you right away!\n"
        f"*(You have **{USER_RESPONSE_WAIT} seconds** to send your first message. "
        f"If you need more time, don't worry — I'll wait for you!)*"
    )

    # Check function
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

    # Wait 30 seconds for first message
    first_msg = None

    try:
        from main import bot
        first_msg = await bot.wait_for("message", check=check, timeout=USER_RESPONSE_WAIT)

    except asyncio.TimeoutError:
        if active_tickets[channel_id]["stopped"]:
            return

        # Switch to wait mode
        active_tickets[channel_id]["waiting"] = True

        await channel.send(
            f"⏳ **{BOT_NAME}:** No worries, take your time! "
            f"I'm still here whenever you're ready to describe your issue."
        )

        print(f"[Ticket] #{channel.name} entered wait mode")

        # Wait indefinitely
        try:
            from main import bot
            first_msg = await bot.wait_for("message", check=check, timeout=None)
        except Exception as e:
            print(f"[Ticket] Wait mode error: {e}")
            return

    if active_tickets[channel_id]["stopped"]:
        return

    active_tickets[channel_id]["waiting"] = False

    # Add to conversation
    active_tickets[channel_id]["conversation"].append({
        "role": "user",
        "content": first_msg.content
    })

    # Generate AI response
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

    # Send summary and ping staff
    await send_summary(channel, guild, channel_id, version=1)


async def send_summary(
    channel: discord.TextChannel,
    guild: discord.Guild,
    channel_id: int,
    version: int = 1
):
    """Create and send/update the ticket summary"""

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
        print(f"[Summary] v{version} sent in #{channel.name}")
    else:
        try:
            await existing_summary.edit(content=full_message)
            print(f"[Summary] v{version} updated in #{channel.name}")
        except discord.NotFound:
            summary_msg = await channel.send(full_message)
            active_tickets[channel_id]["summary_msg"] = summary_msg


async def handle_followup_message(message: discord.Message, guild: discord.Guild):
    """Handle follow-up messages after the first AI response"""

    channel_id = message.channel.id
    ticket = active_tickets.get(channel_id)

    if not ticket:
        return
    if ticket["stopped"]:
        return
    if message.author.bot:
        return

    # User check
    user = ticket.get("user")
    if user and message.author.id != user.id:
        return

    # Add to conversation
    ticket["conversation"].append({
        "role": "user",
        "content": message.content
    })

    # Generate AI response
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

    # Update summary version
    user_message_count = len([m for m in ticket["conversation"] if m["role"] == "user"])
    await send_summary(message.channel, guild, channel_id, version=user_message_count)


def stop_ticket(channel_id: int) -> bool:
    """Stop the bot in a ticket channel"""
    if channel_id in active_tickets:
        active_tickets[channel_id]["stopped"] = True
        return True
    return False


def is_active_ticket(channel_id: int) -> bool:
    return channel_id in active_tickets and not active_tickets[channel_id]["stopped"]
