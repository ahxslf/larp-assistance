import asyncio
import discord
from config import (
    INITIAL_WAIT, USER_RESPONSE_WAIT,
    STAFF_PING_ID, STAFF_ROLE_ID, BOT_NAME
)
from handlers.ai_handler import AIHandler

ai = AIHandler()

active_tickets: dict[int, dict] = {}

# Komut prefixleri — bu ile başlayan mesajlar AI'ya gitmesin
COMMAND_PREFIXES = ("!", "s!")

def extract_username_from_channel_name(channel_name: str) -> str:
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

def _dedupe_members(members: list[discord.Member]) -> list[discord.Member]:
    unique: dict[int, discord.Member] = {}
    for member in members:
        unique[member.id] = member
    return list(unique.values())

def infer_ticket_owner(channel: discord.TextChannel, guild: discord.Guild) -> discord.Member | None:
    """
    Try to determine the ticket owner without relying on the channel name.

    Strategy:
    1) Prefer explicit member overwrites on the channel.
    2) Prefer non-staff members among those explicit overwrites.
    3) Fall back to broader permission checks.
    4) Only if needed, fall back to the old channel-name heuristic.
    """
    staff_role = guild.get_role(STAFF_ROLE_ID)

    explicit_members: list[discord.Member] = []
    for target, overwrite in channel.overwrites.items():
        if not isinstance(target, discord.Member):
            continue
        if target.bot:
            continue
        if (
            overwrite.view_channel is True
            or overwrite.read_messages is True
            or overwrite.send_messages is True
        ):
            explicit_members.append(target)

    explicit_members = _dedupe_members(explicit_members)
    non_staff_explicit = [
        member for member in explicit_members
        if not staff_role or staff_role not in member.roles
    ]

    if len(non_staff_explicit) == 1:
        return non_staff_explicit[0]
    if len(explicit_members) == 1:
        return explicit_members[0]

    accessible_members: list[discord.Member] = []
    for member in guild.members:
        if member.bot:
            continue

        perms = channel.permissions_for(member)
        can_view = getattr(perms, "view_channel", getattr(perms, "read_messages", False))
        can_send = getattr(perms, "send_messages", False)
        if can_view and can_send:
            accessible_members.append(member)

    accessible_members = _dedupe_members(accessible_members)
    non_staff_accessible = [
        member for member in accessible_members
        if not staff_role or staff_role not in member.roles
    ]

    if len(non_staff_accessible) == 1:
        return non_staff_accessible[0]
    if len(accessible_members) == 1:
        return accessible_members[0]

    username = extract_username_from_channel_name(channel.name)
    return find_member_by_username(guild, username)

def is_command_message(content: str) -> bool:
    """Mesaj bir komutsa True döner — AI buna cevap vermez."""
    for prefix in COMMAND_PREFIXES:
        if content.startswith(prefix):
            return True
    return False

async def handle_new_ticket(bot, channel: discord.TextChannel, guild: discord.Guild):
    channel_id = channel.id

    active_tickets[channel_id] = {
        "stopped": False,
        "waiting": False,
        "first_message_done": False,
        "conversation": [],
        "summary_msg": None,
        "last_summary_count": 0,
        "user": None,
    }

    await asyncio.sleep(INITIAL_WAIT)

    if active_tickets[channel_id]["stopped"]:
        return

    member = infer_ticket_owner(channel, guild)
    active_tickets[channel_id]["user"] = member

    owner_label = member.display_name if member else "unknown"
    print(f"[Ticket] New ticket: #{channel.name} | Owner: {owner_label}")

    intro = (
        f"{member.mention} 👋 Hello! I'm **{BOT_NAME}**, your automated support assistant.\n\n"
        if member else
        f"👋 Hello! I'm **{BOT_NAME}**, your automated support assistant.\n\n"
    )

    await channel.send(
        intro
        + f"Please describe your issue and I'll do my best to help you right away!\n"
        + f"*(You have **{USER_RESPONSE_WAIT} seconds** to send your first message. "
        + f"If you need more time, don't worry — I'll wait for you!)*"
    )

    def check(m: discord.Message) -> bool:
        if active_tickets.get(channel_id, {}).get("stopped"):
            return False
        if m.author.bot:
            return False
        if m.channel.id != channel_id:
            return False
        # Komut mesajlarını yoksay
        if is_command_message(m.content):
            return False

        ticket_user = active_tickets.get(channel_id, {}).get("user")
        if ticket_user:
            return m.author.id == ticket_user.id
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

async def send_summary(
    channel: discord.TextChannel,
    guild: discord.Guild,
    channel_id: int,
    version: int = 1
):
    if active_tickets[channel_id]["stopped"]:
        return

    conversation = active_tickets[channel_id]["conversation"]
    escalate, summary_text = await ai.generate_summary(conversation)

    # If the AI decided this is a trivial ticket (just a question that was
    # already answered, nothing for a human to do), don't post a summary and
    # don't ping the staff team.
    if not escalate:
        print(f"[Ticket] #{channel.name}: trivial ticket, skipping summary/ping.")
        return

    # Don't spam: only post a new summary if something new actually happened
    # since the last one we sent.
    last_count = active_tickets[channel_id].get("last_summary_count", 0)
    if version <= last_count:
        return

    staff_role = guild.get_role(STAFF_PING_ID)
    staff_mention = staff_role.mention if staff_role else "@Staff"

    full_message = (
        f"{'━' * 35}\n"
        f"📊 **TICKET SUMMARY v{version}** — {staff_mention}\n"
        f"{'━' * 35}\n"
        f"{summary_text}\n"
        f"{'━' * 35}"
    )

    # Always post a NEW message instead of editing the previous summary.
    summary_msg = await channel.send(full_message)
    active_tickets[channel_id]["summary_msg"] = summary_msg
    active_tickets[channel_id]["last_summary_count"] = version

async def handle_followup_message(message: discord.Message, guild: discord.Guild):
    channel_id = message.channel.id
    ticket = active_tickets.get(channel_id)

    if not ticket:
        return
    if ticket["stopped"]:
        return
    if message.author.bot:
        return

    # Komut mesajlarını yoksay
    if is_command_message(message.content):
        return

    # Sadece ticket sahibi konuşabilir
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

    # Summary: kullanıcı en az 2 mesaj gönderdikten sonra
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

def is_known_ticket(channel_id: int) -> bool:
    """True if the bot has any state for this ticket (active OR stopped)."""
    return channel_id in active_tickets

# ───────────────────────────────────────────
# HISTORY REBUILD
# ───────────────────────────────────────────

# Prefix the bot prepends to its own messages, e.g. "**LARP | Assistance:** ..."
_BOT_PREFIX = f"**{BOT_NAME}:**"

def _looks_like_bot_message(content: str) -> bool:
    return content.startswith(_BOT_PREFIX) or content.startswith(f"**{BOT_NAME}**")

def _strip_bot_prefix(content: str) -> str:
    if content.startswith(_BOT_PREFIX):
        return content[len(_BOT_PREFIX):].strip()
    return content.strip()

async def rebuild_conversation_from_history(
    bot,
    channel: discord.TextChannel,
    ticket_user: "discord.Member | None",
    limit: int = 500,
) -> list[dict]:
    """
    Read the channel's message history and reconstruct the AI conversation
    list so the bot can continue with full context.

    - Messages authored by the bot that start with the bot prefix  -> assistant
    - Messages authored by the ticket user (no command prefix)     -> user
    Other messages (staff chatter, system/embeds, commands) are ignored so
    the AI context stays clean.
    """
    conversation: list[dict] = []

    async for msg in channel.history(limit=limit, oldest_first=True):
        content = (msg.content or "").strip()
        if not content:
            continue

        if msg.author.id == bot.user.id:
            # Only treat the bot's actual AI replies as assistant turns.
            if _looks_like_bot_message(content):
                conversation.append({
                    "role": "assistant",
                    "content": _strip_bot_prefix(content),
                })
            continue

        if msg.author.bot:
            continue

        # Skip command messages
        if is_command_message(content):
            continue

        # Only count the ticket owner's messages as user turns (if we know them)
        if ticket_user and msg.author.id != ticket_user.id:
            continue

        conversation.append({"role": "user", "content": content})

    return conversation

async def resume_ticket(bot, channel: discord.TextChannel, guild: discord.Guild) -> dict:
    """
    `!start` — Re-enable the bot in a ticket that was previously disabled
    (e.g. via !stop). The bot reads the full message history and rebuilds its
    conversation context so it can keep answering with awareness of what was
    already said.

    Returns a status dict: {"status": "...", ...}
    """
    channel_id = channel.id
    ticket = active_tickets.get(channel_id)

    if ticket is None:
        # No in-memory state at all — this is really a restart case.
        return {"status": "no_state"}

    if not ticket.get("stopped"):
        return {"status": "already_active"}

    # Determine / refresh the ticket owner
    member = ticket.get("user")
    if member is None:
        member = infer_ticket_owner(channel, guild)
        ticket["user"] = member

    # Re-read history so context is fully up to date
    conversation = await rebuild_conversation_from_history(bot, channel, member)
    ticket["conversation"] = conversation

    # Re-enable
    ticket["stopped"] = False
    ticket["waiting"] = False
    ticket["first_message_done"] = True
    # Allow new summaries again from this point
    ticket["last_summary_count"] = 0

    print(f"[Ticket] Resumed #{channel.name} ({len(conversation)} msgs in context).")
    return {"status": "resumed", "messages": len(conversation)}

async def restart_ticket(bot, channel: discord.TextChannel, guild: discord.Guild) -> dict:
    """
    `!restart` — Rebuild a ticket from scratch after the bot was restarted by
    the host (maintenance / redeploy). In that situation the in-memory state is
    gone and the ticket got silently deactivated. This recreates the ticket
    state and reloads context from the channel history so the bot is live again.

    Returns a status dict: {"status": "...", ...}
    """
    channel_id = channel.id
    member = infer_ticket_owner(channel, guild)

    conversation = await rebuild_conversation_from_history(bot, channel, member)

    active_tickets[channel_id] = {
        "stopped": False,
        "waiting": False,
        "first_message_done": True,
        "conversation": conversation,
        "summary_msg": None,
        "last_summary_count": 0,
        "user": member,
    }

    print(f"[Ticket] Restarted #{channel.name} ({len(conversation)} msgs in context).")
    return {"status": "restarted", "messages": len(conversation)}
