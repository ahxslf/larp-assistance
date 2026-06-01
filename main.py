import discord
import asyncio
from discord.ext import commands
from config import DISCORD_TOKEN, TICKET_CATEGORY_ID, STAFF_ROLE_ID
from handlers.ticket_handler import (
    handle_new_ticket, handle_followup_message,
    stop_ticket, is_active_ticket, is_first_message_done,
    active_tickets
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    print(f"📂 Watching category ID: {TICKET_CATEGORY_ID}")


@bot.event
async def on_guild_channel_create(channel):
    if not isinstance(channel, discord.TextChannel):
        return
    if not channel.category or channel.category.id != TICKET_CATEGORY_ID:
        return
    if not channel.name.startswith("support-"):
        return

    print(f"[+] Ticket detected: #{channel.name}")
    asyncio.create_task(handle_new_ticket(bot, channel, channel.guild))


@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)

    if message.author.bot:
        return
    if not message.guild:
        return
    if not message.channel.category:
        return
    if message.channel.category.id != TICKET_CATEGORY_ID:
        return
    if not message.channel.name.startswith("support-"):
        return

    channel_id = message.channel.id

    if not is_active_ticket(channel_id):
        return

    ticket = active_tickets.get(channel_id)
    if not ticket:
        return

    if ticket.get("waiting", False):
        return

    if not is_first_message_done(channel_id):
        return

    await handle_followup_message(message, message.guild)


@bot.command(name="stop")
async def stop_command(ctx: commands.Context):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission.")
        return

    if not is_active_ticket(ctx.channel.id):
        await ctx.send("❌ Not an active ticket.")
        return

    stop_ticket(ctx.channel.id)
    await ctx.send("🛑 LARP | Assistance disabled.")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
