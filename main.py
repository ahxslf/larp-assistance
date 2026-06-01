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

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot is online: {bot.user} (ID: {bot.user.id})")
    print(f"📂 Watching category ID: {TICKET_CATEGORY_ID}")
    print(f"📋 Guilds: {[g.name for g in bot.guilds]}")
    
    # Kategoriyi kontrol et
    for guild in bot.guilds:
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category:
            print(f"✅ Category found: {category.name} in {guild.name}")
        else:
            print(f"❌ Category NOT found in {guild.name}! ID: {TICKET_CATEGORY_ID}")


@bot.event
async def on_guild_channel_create(channel):
    print(f"[DEBUG] Channel created: {channel.name} | Type: {type(channel)} | Category: {channel.category}")
    
    if not isinstance(channel, discord.TextChannel):
        print(f"[DEBUG] Skipped — not a text channel")
        return

    if not channel.category or channel.category.id != TICKET_CATEGORY_ID:
        print(f"[DEBUG] Skipped — wrong category. Got: {channel.category.id if channel.category else 'None'} | Expected: {TICKET_CATEGORY_ID}")
        return

    if not channel.name.startswith("support-"):
        print(f"[DEBUG] Skipped — name doesn't start with 'support-'. Got: {channel.name}")
        return

    print(f"[+] ✅ Ticket channel detected: #{channel.name}")
    asyncio.create_task(handle_new_ticket(channel, channel.guild))


@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)

    if message.author.bot:
        return
    if not message.guild:
        return
    if message.content.startswith("!stop"):
        return

    # Debug — her mesajı logla
    if message.channel.category and message.channel.category.id == TICKET_CATEGORY_ID:
        print(f"[MSG] #{message.channel.name} | {message.author}: {message.content[:50]}")

    if not is_active_ticket(message.channel.id):
        return

    if not message.channel.category:
        return
    if message.channel.category.id != TICKET_CATEGORY_ID:
        return
    if not message.channel.name.startswith("support-"):
        return

    ticket = active_tickets.get(message.channel.id)
    if ticket and not ticket.get("waiting", False):
        conversation = ticket.get("conversation", [])
        if len(conversation) >= 2:
            await handle_followup_message(message, message.guild)


@bot.command(name="stop")
async def stop_command(ctx: commands.Context):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if staff_role not in ctx.author.roles:
        await ctx.send("❌ You don't have permission to use this command.", delete_after=5)
        return

    if not is_active_ticket(ctx.channel.id):
        await ctx.send("❌ This is not an active ticket channel.", delete_after=5)
        return

    success = stop_ticket(ctx.channel.id)

    if success:
        await ctx.send(
            "🛑 **LARP | Assistance has been disabled in this channel.**\n"
            "A staff member will assist you shortly."
        )
        print(f"[Stop] Bot stopped in #{ctx.channel.name} by {ctx.author}")
    else:
        await ctx.send("❌ Could not stop the bot.", delete_after=5)


# ── Render sleep önlemek için basit HTTP server ──
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    
    def log_message(self, format, *args):
        pass  # HTTP loglarını sustur

def run_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

# Health server'ı ayrı thread'de başlat
threading.Thread(target=run_health_server, daemon=True).start()
print("🌐 Health check server started on port 8080")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
