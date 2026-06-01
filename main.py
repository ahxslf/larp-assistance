import discord
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands
from config import DISCORD_TOKEN, TICKET_CATEGORY_ID, STAFF_ROLE_ID
from handlers.ticket_handler import (
    handle_new_ticket, handle_followup_message,
    stop_ticket, is_active_ticket, is_first_message_done,
    active_tickets
)

# Render web service için minimal HTTP server
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_http_server():
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    server.serve_forever()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

def is_staff(ctx: commands.Context) -> bool:
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    return staff_role in ctx.author.roles

def is_ticket_channel(ctx: commands.Context) -> bool:
    return (
        ctx.channel.category is not None
        and ctx.channel.category.id == TICKET_CATEGORY_ID
        and ctx.channel.name.startswith("support-")
    )

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

# ───────────────────────────────────────────
# KOMUTLAR
# ───────────────────────────────────────────

@bot.command(name="stop")
async def stop_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not is_active_ticket(ctx.channel.id):
        await ctx.send("❌ Not an active ticket.")
        return
    stop_ticket(ctx.channel.id)
    await ctx.send("🛑 LARP | Assistance disabled.")

@bot.command(name="claim")
async def claim_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    # Kanala staff'ın adını tag olarak yaz, konuya ekle
    await ctx.channel.edit(topic=f"Claimed by {ctx.author.display_name}")
    await ctx.send(f"✅ Ticket claimed by {ctx.author.mention}.")

@bot.command(name="unclaim")
async def unclaim_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    await ctx.channel.edit(topic=None)
    await ctx.send("✅ Ticket unclaimed.")

@bot.command(name="rename")
async def rename_command(ctx: commands.Context, *, new_name: str = None):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not new_name:
        await ctx.send("❌ Usage: `!rename <new name>`")
        return
    # Discord kanal isimleri boşluk içeremez, tire yap
    safe_name = new_name.lower().replace(" ", "-")
    await ctx.channel.edit(name=f"support-{safe_name}")
    await ctx.send(f"✅ Channel renamed to `support-{safe_name}`.")

@bot.command(name="remove")
async def remove_command(ctx: commands.Context, member: discord.Member = None):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not member:
        await ctx.send("❌ Usage: `!remove @user`")
        return
    await ctx.channel.set_permissions(member, overwrite=None)
    await ctx.send(f"✅ {member.mention} removed from this ticket.")

@bot.command(name="add")
async def add_command(ctx: commands.Context, member: discord.Member = None):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
    if not member:
        await ctx.send("❌ Usage: `!add @user`")
        return
    await ctx.channel.set_permissions(member,
        read_messages=True,
        send_messages=True
    )
    await ctx.send(f"✅ {member.mention} added to this ticket.")

if __name__ == "__main__":
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
    print("🌐 HTTP health server started on port 10000")
    bot.run(DISCORD_TOKEN)
