import discord
import asyncio
from discord.ext import commands
from config import (
    DISCORD_TOKEN, TICKET_CATEGORY_ID,
    STAFF_ROLE_ID
)
from handlers.ticket_handler import (
    handle_new_ticket, handle_followup_message,
    stop_ticket, is_active_ticket, active_tickets
)

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot is online: {bot.user}")
    print(f"📂 Watching category ID: {TICKET_CATEGORY_ID}")


@bot.event
async def on_guild_channel_create(channel: discord.TextChannel):
    """Triggers when a new channel is created"""

    # Text channels only
    if not isinstance(channel, discord.TextChannel):
        return

    # Correct category?
    if not channel.category or channel.category.id != TICKET_CATEGORY_ID:
        return

    # Starts with "support-"?
    if not channel.name.startswith("support-"):
        return

    print(f"[+] Ticket channel detected: #{channel.name}")

    # Start as async task to avoid blocking
    asyncio.create_task(handle_new_ticket(channel, channel.guild))


@bot.event
async def on_message(message: discord.Message):
    """Triggers on every message"""

    # Process commands first
    await bot.process_commands(message)

    # Ignore bots
    if message.author.bot:
        return

    # Ignore DMs
    if not message.guild:
        return

    # Ignore !stop (handled by command)
    if message.content.startswith("!stop"):
        return

    # Is this an active ticket channel?
    if not is_active_ticket(message.channel.id):
        return

    # Category check
    if not message.channel.category:
        return
    if message.channel.category.id != TICKET_CATEGORY_ID:
        return

    # support- channel?
    if not message.channel.name.startswith("support-"):
        return

    # Only handle follow-up messages (after at least 1 AI response)
    ticket = active_tickets.get(message.channel.id)
    if ticket and not ticket.get("waiting", False):
        conversation = ticket.get("conversation", [])
        # At least 1 user message + 1 AI response means first exchange is done
        if len(conversation) >= 2:
            await handle_followup_message(message, message.guild)


@bot.command(name="stop")
async def stop_command(ctx: commands.Context):
    """!stop — Disables the bot in this ticket channel (Staff only)"""

    # Staff role check
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send(
            "❌ You don't have permission to use this command.",
            delete_after=5
        )
        return

    # Active ticket check
    if not is_active_ticket(ctx.channel.id):
        await ctx.send(
            "❌ This is not an active ticket channel.",
            delete_after=5
        )
        return

    # Stop the bot
    success = stop_ticket(ctx.channel.id)

    if success:
        await ctx.send(
            "🛑 **LARP | Assistance has been disabled in this channel.**\n"
            "A staff member will assist you shortly."
        )
        print(f"[Stop] Bot stopped in #{ctx.channel.name} by {ctx.author}")
    else:
        await ctx.send("❌ Could not stop the bot.", delete_after=5)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
