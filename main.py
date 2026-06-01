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

# ✅ Önce intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# ✅ Sonra bot tanımı
bot = commands.Bot(command_prefix="!", intents=intents)

# ─────────────────────────────
# ✅ HEALTH SERVER
# ─────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):

    def _send_ok(self):
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return body

    def do_GET(self):
        if self.path in ["/", "/healthz"]:
            body = self._send_ok()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        if self.path in ["/", "/healthz"]:
            self._send_ok()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return


def run_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()
print("🌐 Health check server started on port 8080")

# ─────────────────────────────
# ✅ DISCORD EVENTS
# ─────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    print(f"📂 Watching category: {TICKET_CATEGORY_ID}")


@bot.event
async def on_guild_channel_create(channel):
    if not isinstance(channel, discord.TextChannel):
        return
    if not channel.category or channel.category.id != TICKET_CATEGORY_ID:
        return
    if not channel.name.startswith("support-"):
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
    await ctx.send("🛑 LARP | Assistance disabled in this channel.")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
