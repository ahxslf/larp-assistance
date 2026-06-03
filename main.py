import discord
import asyncio
import threading
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands
from config import (
    DISCORD_TOKEN, TICKET_CATEGORY_ID, STAFF_ROLE_ID,
    TRANSCRIPT_CHANNEL_ID, FOUNDERSHIP_TEAM_ROLE_ID, FASTPASS_TEAM_ROLE_ID,
    MANAGEMENT_TEAM_ROLE_ID, DIRECTIVE_TEAM_ROLE_ID,
    PARTNERSHIP_CHANNEL_ID,
    ROLE_LEAD_ADMIN, ROLE_SENIOR_ADMIN, ROLE_ADMIN, ROLE_JUNIOR_ADMIN, ROLE_TRIAL_ADMIN,
    ROLE_ADMINISTRATION_TEAM,
    ROLE_LEAD_MOD, ROLE_SENIOR_MOD, ROLE_MOD, ROLE_JUNIOR_MOD, ROLE_TRIAL_MOD,
    ROLE_MODERATION_TEAM, ROLE_STAFF_TEAM
)
from handlers.ticket_handler import (
    handle_new_ticket, handle_followup_message,
    stop_ticket, is_active_ticket, is_first_message_done,
    active_tickets
)

# ───────────────────────────────────────────
# HTTP SERVER
# ───────────────────────────────────────────

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

# ───────────────────────────────────────────
# BOT SETUP
# ───────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

async def get_prefix(bot, message):
    return ["!", "s!"]

bot = commands.Bot(command_prefix=get_prefix, intents=intents)

# ───────────────────────────────────────────
# FASTPASS ROLE DATA
# ───────────────────────────────────────────

FASTPASS_ROLES = [
    ("Lead Administrator",   ROLE_LEAD_ADMIN),
    ("Senior Administrator", ROLE_SENIOR_ADMIN),
    ("Administrator",        ROLE_ADMIN),
    ("Junior Administrator", ROLE_JUNIOR_ADMIN),
    ("Trial Administrator",  ROLE_TRIAL_ADMIN),
    ("Lead Moderator",       ROLE_LEAD_MOD),
    ("Senior Moderator",     ROLE_SENIOR_MOD),
    ("Moderator",            ROLE_MOD),
    ("Junior Moderator",     ROLE_JUNIOR_MOD),
    ("Trial Moderator",      ROLE_TRIAL_MOD),
]

ADMIN_ROLE_IDS = {ROLE_LEAD_ADMIN, ROLE_SENIOR_ADMIN, ROLE_ADMIN, ROLE_JUNIOR_ADMIN, ROLE_TRIAL_ADMIN}
MOD_ROLE_IDS   = {ROLE_LEAD_MOD, ROLE_SENIOR_MOD, ROLE_MOD, ROLE_JUNIOR_MOD, ROLE_TRIAL_MOD}

# ───────────────────────────────────────────
# HELPERS
# ───────────────────────────────────────────

def is_staff(ctx: commands.Context) -> bool:
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    return staff_role in ctx.author.roles

def can_review_application(interaction: discord.Interaction) -> bool:
    """Management Team, Directive Team veya Foundership Team kontrolü."""
    user_role_ids = {r.id for r in interaction.user.roles}
    return bool(user_role_ids & {
        MANAGEMENT_TEAM_ROLE_ID,
        DIRECTIVE_TEAM_ROLE_ID,
        FOUNDERSHIP_TEAM_ROLE_ID,
        FASTPASS_TEAM_ROLE_ID,
    })

def is_ticket_channel(ctx: commands.Context) -> bool:
    return (
        ctx.channel.category is not None
        and ctx.channel.category.id == TICKET_CATEGORY_ID
        and ctx.channel.name.startswith("support-")
    )

def get_ping_text(guild: discord.Guild) -> str:
    """Management Team + Directive Team mention."""
    mgmt = guild.get_role(MANAGEMENT_TEAM_ROLE_ID)
    dire = guild.get_role(DIRECTIVE_TEAM_ROLE_ID)
    parts = []
    if mgmt:
        parts.append(mgmt.mention)
    if dire:
        parts.append(dire.mention)
    return " ".join(parts) if parts else "@Management Team @Directive Team"

async def send_transcript(channel: discord.TextChannel, guild: discord.Guild, closed_by: discord.Member):
    transcript_channel = guild.get_channel(TRANSCRIPT_CHANNEL_ID)
    if not transcript_channel:
        print(f"[Transcript] Channel {TRANSCRIPT_CHANNEL_ID} not found!")
        return
    messages = []
    async for msg in channel.history(limit=500, oldest_first=True):
        timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        content = msg.content or "(no text content)"
        messages.append(f"[{timestamp}] {msg.author.display_name}: {content}")
    transcript_text = "\n".join(messages) if messages else "(No messages)"
    embed = discord.Embed(
        title=f"📋 Ticket Transcript — #{channel.name}",
        color=discord.Color.blurple(),
        description=f"**Closed by:** {closed_by.mention}\n**Channel:** #{channel.name}"
    )
    embed.set_footer(text=f"Ticket closed • {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    file = discord.File(
        fp=io.BytesIO(transcript_text.encode("utf-8")),
        filename=f"transcript-{channel.name}.txt"
    )
    await transcript_channel.send(embed=embed, file=file)
    print(f"[Transcript] Sent for #{channel.name}")

async def give_roles(guild: discord.Guild, applicant: discord.Member, role_id: int, promoted_by: str):
    """Rol ver + otomatik ekstra roller."""
    roles_to_add = [role_id]
    if role_id in ADMIN_ROLE_IDS:
        roles_to_add.append(ROLE_ADMINISTRATION_TEAM)
        roles_to_add.append(ROLE_STAFF_TEAM)
    elif role_id in MOD_ROLE_IDS:
        roles_to_add.append(ROLE_MODERATION_TEAM)
        roles_to_add.append(ROLE_STAFF_TEAM)

    added = []
    failed = []
    for rid in roles_to_add:
        role_obj = guild.get_role(rid)
        if role_obj is None:
            failed.append(str(rid))
            continue
        if role_obj in applicant.roles:
            continue
        try:
            await applicant.add_roles(role_obj, reason=f"Fast Pass by {promoted_by}")
            added.append(role_obj.name)
        except discord.Forbidden:
            failed.append(role_obj.name)
        except Exception as e:
            failed.append(f"{role_obj.name} ({e})")

    return added, failed

# ───────────────────────────────────────────
# ROLE SELECT VIEW (reusable)
# ───────────────────────────────────────────

class RoleSelectView(discord.ui.View):
    """Rol seçim view'ı — ephemeral olarak gönderilir."""

    def __init__(self, applicant: discord.Member, notify_channel: discord.TextChannel, parent_message: discord.Message):
        super().__init__(timeout=120)
        self.applicant = applicant
        self.notify_channel = notify_channel
        self.parent_message = parent_message
        self.add_item(self.RoleDropdown(self))

    class RoleDropdown(discord.ui.Select):
        def __init__(self, parent_view):
            self.parent_view = parent_view
            options = [
                discord.SelectOption(label=name, value=str(role_id))
                for name, role_id in FASTPASS_ROLES
            ]
            super().__init__(
                placeholder="Select a role to assign...",
                options=options,
                min_values=1,
                max_values=1
            )

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)

            selected_id = int(self.values[0])
            selected_name = next(n for n, rid in FASTPASS_ROLES if rid == selected_id)
            applicant = self.parent_view.applicant
            notify_channel = self.parent_view.notify_channel

            added, failed = await give_roles(
                interaction.guild, applicant, selected_id,
                interaction.user.display_name
            )

            added_str = ", ".join(f"**{r}**" for r in added) if added else "*(already had all roles)*"
            fail_str = f"\n⚠️ Failed to assign: {', '.join(failed)}" if failed else ""

            # Üst mesajdaki butonları devre dışı bırak
            try:
                for item in self.parent_view.parent_message.components:
                    pass  # discord.py v2 edit ile yapılır
                # Parent view'ı disable et
                disabled_view = discord.ui.View()
                disabled_view.add_item(
                    discord.ui.Button(label="✅ Promoted", style=discord.ButtonStyle.success, disabled=True)
                )
                await self.parent_view.parent_message.edit(view=disabled_view)
            except Exception:
                pass

            await interaction.followup.send(
                f"✅ **{applicant.display_name}** promoted to **{selected_name}**!\n"
                f"Roles assigned: {added_str}{fail_str}",
                ephemeral=True
            )

            try:
                await notify_channel.send(
                    f"🎉 {applicant.mention} Congratulations! Your application has been **approved**.\n"
                    f"You have been promoted to **{selected_name}**!"
                )
            except Exception:
                pass

            self.parent_view.stop()

# ───────────────────────────────────────────
# APPLICATION REVIEW VIEW
# ───────────────────────────────────────────

class ApplicationReviewView(discord.ui.View):
    """Fast pass / Transfer review — Management + Directive Team."""

    def __init__(self, applicant_id: int, notify_channel_id: int):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.notify_channel_id = notify_channel_id

    @discord.ui.button(label="✅ Promote", style=discord.ButtonStyle.success, emoji="⬆️",
                       custom_id="app_promote")
    async def promote(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_application(interaction):
            await interaction.response.send_message(
                "❌ Only **Management Team** or **Directive Team** can promote applicants.",
                ephemeral=True
            )
            return

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)

        if not applicant:
            await interaction.response.send_message(
                "❌ Could not find the applicant — they may have left the server.",
                ephemeral=True
            )
            return

        # Rol seçim view'ını ephemeral olarak gönder
        # Önce interaction'ı defer et
        await interaction.response.defer(ephemeral=True)

        role_select_view = RoleSelectView(
            applicant=applicant,
            notify_channel=notify_channel,
            parent_message=interaction.message
        )

        await interaction.followup.send(
            f"Select the role to assign to **{applicant.display_name}**:",
            view=role_select_view,
            ephemeral=True
        )

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="✖️",
                       custom_id="app_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_application(interaction):
            await interaction.response.send_message(
                "❌ Only **Management Team** or **Directive Team** can deny applications.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)

        # Butonları devre dışı bırak
        disabled_view = discord.ui.View()
        disabled_view.add_item(
            discord.ui.Button(label="❌ Denied", style=discord.ButtonStyle.danger, disabled=True)
        )
        try:
            await interaction.message.edit(view=disabled_view)
        except Exception:
            pass

        name = applicant.display_name if applicant else "Unknown"
        await interaction.followup.send(
            f"❌ Application from **{name}** has been **denied**."
        )

        if notify_channel and applicant:
            try:
                await notify_channel.send(
                    f"❌ {applicant.mention} Unfortunately, your application has been **denied**."
                )
            except Exception:
                pass

# ───────────────────────────────────────────
# PARTNERSHIP REVIEW VIEW
# ───────────────────────────────────────────

class PartnershipReviewView(discord.ui.View):
    """Partnership review — Management + Directive Team."""

    def __init__(self, applicant_id: int, notify_channel_id: int, form_content: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.notify_channel_id = notify_channel_id
        self.form_content = form_content

    @discord.ui.button(label="✅ Approve & Post", style=discord.ButtonStyle.success, emoji="🤝",
                       custom_id="partner_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_application(interaction):
            await interaction.response.send_message(
                "❌ Only **Management Team** or **Directive Team** can approve partnerships.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)
        partner_channel = interaction.guild.get_channel(PARTNERSHIP_CHANNEL_ID)

        disabled_view = discord.ui.View()
        disabled_view.add_item(
            discord.ui.Button(label="✅ Approved", style=discord.ButtonStyle.success, disabled=True)
        )
        try:
            await interaction.message.edit(view=disabled_view)
        except Exception:
            pass

        if partner_channel:
            post_embed = discord.Embed(
                title="🤝 New Partnership",
                description=self.form_content,
                color=discord.Color.green()
            )
            post_embed.set_footer(text=f"Approved by {interaction.user.display_name}")
            await partner_channel.send("@everyone", embed=post_embed)

        ch_mention = partner_channel.mention if partner_channel else "#partnerships"
        await interaction.followup.send(f"✅ Partnership approved and posted to {ch_mention}!")

        if notify_channel and applicant:
            try:
                await notify_channel.send(
                    f"🎉 {applicant.mention} Your partnership application has been **approved** and posted!"
                )
            except Exception:
                pass

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="✖️",
                       custom_id="partner_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_review_application(interaction):
            await interaction.response.send_message(
                "❌ Only **Management Team** or **Directive Team** can deny partnerships.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)

        disabled_view = discord.ui.View()
        disabled_view.add_item(
            discord.ui.Button(label="❌ Denied", style=discord.ButtonStyle.danger, disabled=True)
        )
        try:
            await interaction.message.edit(view=disabled_view)
        except Exception:
            pass

        name = applicant.display_name if applicant else "Unknown"
        await interaction.followup.send(f"❌ Partnership from **{name}** denied.")

        if notify_channel and applicant:
            try:
                await notify_channel.send(
                    f"❌ {applicant.mention} Unfortunately, your partnership application has been **denied**."
                )
            except Exception:
                pass

# ───────────────────────────────────────────
# EVENTS
# ───────────────────────────────────────────

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

    # Komut mesajlarını AI'ya gönderme
    if message.content.startswith("!") or message.content.startswith("s!"):
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

    # Sadece ticket sahibinin mesajları işlensin
    ticket_user = ticket.get("user")
    if ticket_user and message.author.id != ticket_user.id:
        return

    if ticket.get("waiting", False):
        return
    if not is_first_message_done(channel_id):
        return

    await handle_followup_message(message, message.guild)

# ───────────────────────────────────────────
# TICKET COMMANDS
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

@bot.command(name="close")
async def close_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            self.confirmed = None

        @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Only the command user can confirm.", ephemeral=True)
                return
            self.confirmed = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message("❌ Only the command user can cancel.", ephemeral=True)
                return
            self.confirmed = False
            self.stop()
            await interaction.response.defer()

    view = ConfirmView()
    confirm_msg = await ctx.send(
        "⚠️ Are you sure you want to close this ticket?\n"
        "The ticket will be **deleted in 30 seconds** after confirmation.",
        view=view
    )
    await view.wait()

    if view.confirmed is None:
        for item in view.children:
            item.disabled = True
        await confirm_msg.edit(content="⏰ Close request timed out. Ticket was **not** closed.", view=view)
        return

    if not view.confirmed:
        for item in view.children:
            item.disabled = True
        await confirm_msg.edit(content="❌ Ticket close **cancelled**.", view=view)
        return

    for item in view.children:
        item.disabled = True
    await confirm_msg.edit(content="✅ Ticket confirmed for closure. Sending transcript...", view=view)

    stop_ticket(ctx.channel.id)
    await send_transcript(ctx.channel, ctx.guild, ctx.author)

    countdown_msg = await ctx.send("🗑️ This ticket will be deleted in **30 seconds**...")
    for i in [25, 20, 15, 10, 5]:
        await asyncio.sleep(5)
        try:
            await countdown_msg.edit(content=f"🗑️ This ticket will be deleted in **{i} seconds**...")
        except Exception:
            pass
    await asyncio.sleep(5)

    try:
        await ctx.channel.delete(reason=f"Ticket closed by {ctx.author.display_name}")
    except Exception as e:
        print(f"[Close] Failed to delete channel: {e}")

@bot.command(name="claim")
async def claim_command(ctx: commands.Context):
    if not is_staff(ctx):
        await ctx.send("❌ You don't have permission.")
        return
    if not is_ticket_channel(ctx):
        await ctx.send("❌ This is not a ticket channel.")
        return
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
    await ctx.channel.set_permissions(member, read_messages=True, send_messages=True)
    await ctx.send(f"✅ {member.mention} added to this ticket.")

# ───────────────────────────────────────────
# !cmds
# ───────────────────────────────────────────

@bot.command(name="cmds")
async def cmds_command(ctx: commands.Context):
    embed = discord.Embed(
        title="📖 LARP | Assistance — Commands",
        color=discord.Color.blurple()
    )
    embed.add_field(
        name="🎫 Ticket Commands (`!`)",
        value=(
            "`!stop` — Disable AI assistance in this ticket\n"
            "`!close` — Close & delete ticket (confirmation + transcript)\n"
            "`!claim` — Claim this ticket\n"
            "`!unclaim` — Unclaim this ticket\n"
            "`!rename <name>` — Rename the ticket channel\n"
            "`!add @user` — Add a user to this ticket\n"
            "`!remove @user` — Remove a user from this ticket"
        ),
        inline=False
    )
    embed.add_field(
        name="⚡ Application Commands (`s!`) — Open to all",
        value=(
            "`s!fastpass` — Submit a Fast Pass application\n"
            "`s!transfer` — Submit a Transfer / Retirement application\n"
            "`s!partnership` — Submit a Partnership application"
        ),
        inline=False
    )
    embed.add_field(
        name="🔒 Management Team / Directive Team Only",
        value="Promote/Deny/Approve buttons on submitted applications.",
        inline=False
    )
    embed.set_footer(text="LARP | Assistance • Los Angeles Roleplay")
    await ctx.send(embed=embed)

# ───────────────────────────────────────────
# SHARED: rate limit helper
# ───────────────────────────────────────────

RATE_LIMIT_SECONDS = 40

# ───────────────────────────────────────────
# s!fastpass
# ───────────────────────────────────────────

@bot.command(name="fastpass")
async def fastpass_command(ctx: commands.Context):
    applicant = ctx.author
    channel = ctx.channel

    def check_author(m):
        return (
            m.author.id == applicant.id
            and m.channel.id == channel.id
            and not m.content.startswith("!")
            and not m.content.startswith("s!")
        )

    # Transfer mi?
    class TransferView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.is_transfer = None

        @discord.ui.button(label="✅ Yes — Transfer", style=discord.ButtonStyle.primary)
        async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.is_transfer = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="❌ No — Standard", style=discord.ButtonStyle.secondary)
        async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.is_transfer = False
            self.stop()
            await interaction.response.defer()

    transfer_view = TransferView()
    await ctx.send("📋 **Fast Pass Application**\n\nIs this a **transfer** from another server?", view=transfer_view)
    await transfer_view.wait()

    if transfer_view.is_transfer is None:
        await ctx.send("⏰ Application timed out.")
        return

    is_transfer = transfer_view.is_transfer
    if is_transfer:
        form_text = (
            "📋 **Fast Pass Application — Transfer**\n\n"
            "Fill in **all fields** and send in **one message**:\n\n"
            "```\n"
            "1. Discord Username:\n"
            "2. Roblox Username:\n"
            "3. What will you bring:\n"
            "4. Strengths:\n"
            "5. Weaknesses:\n"
            "6. Proof of roles (screenshot/link):\n"
            "7. Proof of Retirement (screenshot/link):\n"
            "```"
        )
        app_type = "🔄 Transfer"
    else:
        form_text = (
            "📋 **Fast Pass Application — Standard**\n\n"
            "Fill in **all fields** and send in **one message**:\n\n"
            "```\n"
            "1. Discord Username:\n"
            "2. Roblox Username:\n"
            "3. What will you bring:\n"
            "4. Strengths:\n"
            "5. Weaknesses:\n"
            "6. Proof of roles (screenshot/link):\n"
            "```"
        )
        app_type = "📝 Standard"

    await ctx.send(form_text)

    try:
        response_msg = await bot.wait_for("message", check=check_author, timeout=RATE_LIMIT_SECONDS * 15)
    except asyncio.TimeoutError:
        await ctx.send("⏰ Application timed out. Please try again with `s!fastpass`.")
        return

    form_content = response_msg.content

    # Preview
    preview_embed = discord.Embed(
        title="📋 Fast Pass Application — Preview",
        description=form_content,
        color=discord.Color.gold()
    )
    preview_embed.add_field(name="Type", value=app_type, inline=True)
    preview_embed.add_field(name="Applicant", value=applicant.mention, inline=True)
    preview_embed.set_footer(text="Does everything look correct? Confirm to submit.")

    class PreviewView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.confirmed = None

        @discord.ui.button(label="✅ Submit", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.confirmed = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.confirmed = False
            self.stop()
            await interaction.response.defer()

    preview_view = PreviewView()
    await ctx.send(embed=preview_embed, view=preview_view)
    await preview_view.wait()

    if not preview_view.confirmed:
        await ctx.send("❌ Application cancelled.")
        return

    ping_text = get_ping_text(ctx.guild)

    submission_embed = discord.Embed(
        title="⚡ New Fast Pass Application",
        description=form_content,
        color=discord.Color.blurple()
    )
    submission_embed.add_field(name="Type", value=app_type, inline=True)
    submission_embed.add_field(name="Applicant", value=f"{applicant.mention} (`{applicant.name}`)", inline=True)
    submission_embed.add_field(name="Channel", value=channel.mention, inline=True)
    submission_embed.set_footer(text=f"Submitted • {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    review_view = ApplicationReviewView(applicant_id=applicant.id, notify_channel_id=channel.id)
    await ctx.send(f"{ping_text} — New Fast Pass application!", embed=submission_embed, view=review_view)
    await ctx.send(
        f"✅ {applicant.mention} Your application has been submitted! "
        f"**Management Team** and **Directive Team** have been notified."
    )

# ───────────────────────────────────────────
# s!transfer
# ───────────────────────────────────────────

@bot.command(name="transfer")
async def transfer_command(ctx: commands.Context):
    applicant = ctx.author
    channel = ctx.channel

    def check_author(m):
        return (
            m.author.id == applicant.id
            and m.channel.id == channel.id
            and not m.content.startswith("!")
            and not m.content.startswith("s!")
        )

    await ctx.send(
        "📋 **Transfer / Retirement Application**\n\n"
        "Fill in **all fields** and send in **one message**:\n\n"
        "```\n"
        "1. Discord Username:\n"
        "2. Roblox Username:\n"
        "3. What will you bring:\n"
        "4. Strengths:\n"
        "5. Weaknesses:\n"
        "6. Proof of roles (screenshot/link):\n"
        "7. Proof of Retirement (screenshot/link):\n"
        "```"
    )

    try:
        response_msg = await bot.wait_for("message", check=check_author, timeout=RATE_LIMIT_SECONDS * 15)
    except asyncio.TimeoutError:
        await ctx.send("⏰ Application timed out. Please try again with `s!transfer`.")
        return

    form_content = response_msg.content

    preview_embed = discord.Embed(
        title="🔄 Transfer Application — Preview",
        description=form_content,
        color=discord.Color.gold()
    )
    preview_embed.add_field(name="Type", value="🔄 Transfer / Retirement", inline=True)
    preview_embed.add_field(name="Applicant", value=applicant.mention, inline=True)
    preview_embed.set_footer(text="Does everything look correct? Confirm to submit.")

    class PreviewView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.confirmed = None

        @discord.ui.button(label="✅ Submit", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.confirmed = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.confirmed = False
            self.stop()
            await interaction.response.defer()

    preview_view = PreviewView()
    await ctx.send(embed=preview_embed, view=preview_view)
    await preview_view.wait()

    if not preview_view.confirmed:
        await ctx.send("❌ Application cancelled.")
        return

    ping_text = get_ping_text(ctx.guild)

    submission_embed = discord.Embed(
        title="🔄 New Transfer / Retirement Application",
        description=form_content,
        color=discord.Color.orange()
    )
    submission_embed.add_field(name="Type", value="🔄 Transfer / Retirement", inline=True)
    submission_embed.add_field(name="Applicant", value=f"{applicant.mention} (`{applicant.name}`)", inline=True)
    submission_embed.add_field(name="Channel", value=channel.mention, inline=True)
    submission_embed.set_footer(text=f"Submitted • {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    review_view = ApplicationReviewView(applicant_id=applicant.id, notify_channel_id=channel.id)
    await ctx.send(f"{ping_text} — New Transfer/Retirement application!", embed=submission_embed, view=review_view)
    await ctx.send(
        f"✅ {applicant.mention} Your transfer application has been submitted! "
        f"**Management Team** and **Directive Team** have been notified."
    )

# ───────────────────────────────────────────
# s!partnership
# ───────────────────────────────────────────

@bot.command(name="partnership")
async def partnership_command(ctx: commands.Context):
    applicant = ctx.author
    channel = ctx.channel

    def check_author(m):
        return (
            m.author.id == applicant.id
            and m.channel.id == channel.id
            and not m.content.startswith("!")
            and not m.content.startswith("s!")
        )

    await ctx.send(
        "🤝 **Partnership Application**\n\n"
        "Fill in **all fields** and send in **one message**:\n\n"
        "```\n"
        "Server Name:\n"
        "Server Invite Link:\n"
        "Membercount:\n"
        "Rank in server:\n"
        "Reason:\n"
        "Staff Partnership? (Yes/No):\n"
        "Paying? (Yes/No):\n"
        "```\n"
        "ℹ️ **Staff Partnership** = Cross-server staff fast pass\n"
        "ℹ️ **Paying** = Paid/sponsored partnership"
    )

    try:
        response_msg = await bot.wait_for("message", check=check_author, timeout=RATE_LIMIT_SECONDS * 15)
    except asyncio.TimeoutError:
        await ctx.send("⏰ Application timed out. Please try again with `s!partnership`.")
        return

    form_content = response_msg.content

    preview_embed = discord.Embed(
        title="🤝 Partnership Application — Preview",
        description=form_content,
        color=discord.Color.gold()
    )
    preview_embed.add_field(name="Applicant", value=applicant.mention, inline=True)
    preview_embed.set_footer(text="Does everything look correct? Confirm to submit.")

    class PreviewView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.confirmed = None

        @discord.ui.button(label="✅ Submit", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.confirmed = True
            self.stop()
            await interaction.response.defer()

        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user.id != applicant.id:
                await interaction.response.send_message("❌ This is not your application.", ephemeral=True)
                return
            self.confirmed = False
            self.stop()
            await interaction.response.defer()

    preview_view = PreviewView()
    await ctx.send(embed=preview_embed, view=preview_view)
    await preview_view.wait()

    if not preview_view.confirmed:
        await ctx.send("❌ Application cancelled.")
        return

    ping_text = get_ping_text(ctx.guild)

    submission_embed = discord.Embed(
        title="🤝 New Partnership Application",
        description=form_content,
        color=discord.Color.green()
    )
    submission_embed.add_field(name="Applicant", value=f"{applicant.mention} (`{applicant.name}`)", inline=True)
    submission_embed.add_field(name="Channel", value=channel.mention, inline=True)
    submission_embed.set_footer(text=f"Submitted • {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    review_view = PartnershipReviewView(
        applicant_id=applicant.id,
        notify_channel_id=channel.id,
        form_content=form_content
    )
    await ctx.send(f"{ping_text} — New Partnership application!", embed=submission_embed, view=review_view)
    await ctx.send(
        f"✅ {applicant.mention} Your partnership application has been submitted! "
        f"**Management Team** and **Directive Team** have been notified."
    )

# ───────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────

if __name__ == "__main__":
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
    print("🌐 HTTP health server started on port 10000")
    bot.run(DISCORD_TOKEN)
