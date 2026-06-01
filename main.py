import discord
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands
from config import (
    DISCORD_TOKEN, TICKET_CATEGORY_ID,
    STAFF_ROLE_ID
)
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


# ── Health check server (UptimeRobot için) ──
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # HTTP loglarını sustur

def run_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
print("🌐 Health check server started on port 8080")


@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user} (ID: {bot.user.id})")
    print(f"📂 Watching category ID: {TICKET_CATEGORY_ID}")
    for guild in bot.guilds:
        category = guild.get_channel(TICKET_CATEGORY_ID)
        if category:
            print(f"✅ Category found: '{category.name}' in '{guild.name}'")
        else:
            print(f"❌ Category NOT found in '{guild.name}'!")


@bot.event
async def on_guild_channel_create(channel):
    print(f"[DEBUG] Channel created: {channel.name} | Category: {channel.category.id if channel.category else 'None'}")

    if not isinstance(channel, discord.TextChannel):
        return
    if not channel.category or channel.category.id != TICKET_CATEGORY_ID:
        print(f"[DEBUG] Wrong category, skipping")
        return
    if not channel.name.startswith("support-"):
        print(f"[DEBUG] Name doesn't start with 'support-', skipping")
        return

    print(f"[+] Ticket detected: #{channel.name}")
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
    if not message.channel.category:
        return
    if message.channel.category.id != TICKET_CATEGORY_ID:
        return
    if not message.channel.name.startswith("support-"):
        return

    channel_id = message.channel.id

    print(f"[MSG] #{message.channel.name} | {message.author.name}: {message.content[:60]}")

    # Aktif ticket değilse geç
    if not is_active_ticket(channel_id):
        print(f"[MSG] Not an active ticket, skipping")
        return

    ticket = active_tickets.get(channel_id)
    if not ticket:
        return

    # Wait modundaysa — wait_for zaten yakalıyor, burada işleme
    if ticket.get("waiting", False):
        print(f"[MSG] Ticket in wait mode, wait_for will handle this")
        return

    # İlk mesaj henüz tamamlanmadıysa — wait_for yakalıyor
    if not is_first_message_done(channel_id):
        print(f"[MSG] First message not done yet, wait_for will handle this")
        return

    # İlk exchange tamamlandı, followup mesajı işle
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
        print(f"[Stop] Stopped in #{ctx.channel.name} by {ctx.author}")
    else:
        await ctx.send("❌ Could not stop the bot.", delete_after=5)


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
