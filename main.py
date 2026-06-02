import discord
import asyncio
import threading
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from discord.ext import commands
from config import (
    DISCORD_TOKEN, TICKET_CATEGORY_ID, STAFF_ROLE_ID,
    TRANSCRIPT_CHANNEL_ID, FOUNDERSHIP_TEAM_ROLE_ID, FASTPASS_TEAM_ROLE_ID,
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

def is_fastpass_team(interaction: discord.Interaction) -> bool:
    """Fastpass Team veya Foundership Team kontrolü."""
    guild = interaction.guild
    fp_role = guild.get_role(FASTPASS_TEAM_ROLE_ID)
    founder_role = guild.get_role(FOUNDERSHIP_TEAM_ROLE_ID)
    user_roles = interaction.user.roles
    return (fp_role in user_roles) or (founder_role in user_roles)

def is_ticket_channel(ctx: commands.Context) -> bool:
    return (
        ctx.channel.category is not None
        and ctx.channel.category.id == TICKET_CATEGORY_ID
        and ctx.channel.name.startswith("support-")
    )

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

async def do_promote(interaction: discord.Interaction, applicant: discord.Member, notify_channel: discord.TextChannel):
    """Rol seçim menüsünü ephemeral olarak gönder."""

    class RoleSelect(discord.ui.Select):
        def __init__(self):
            options = [
                discord.SelectOption(label=name, value=str(role_id))
                for name, role_id in FASTPASS_ROLES
            ]
            super().__init__(placeholder="Select a role to assign...", options=options, min_values=1, max_values=1)

        async def callback(self, select_interaction: discord.Interaction):
            await select_interaction.response.defer(ephemeral=True)

            selected_id = int(self.values[0])
            selected_name = next(n for n, rid in FASTPASS_ROLES if rid == selected_id)

            roles_to_add = [selected_id]
            if selected_id in ADMIN_ROLE_IDS:
                roles_to_add.append(ROLE_ADMINISTRATION_TEAM)
                roles_to_add.append(ROLE_STAFF_TEAM)
            elif selected_id in MOD_ROLE_IDS:
                roles_to_add.append(ROLE_MODERATION_TEAM)
                roles_to_add.append(ROLE_STAFF_TEAM)

            added = []
            for rid in roles_to_add:
                role_obj = select_interaction.guild.get_role(rid)
                if role_obj and role_obj not in applicant.roles:
                    await applicant.add_roles(role_obj, reason=f"Fast Pass by {select_interaction.user.display_name}")
                    added.append(role_obj.name)

            added_str = ", ".join(f"**{r}**" for r in added) if added else "*(already had all roles)*"

            await select_interaction.followup.send(
                f"✅ **{applicant.display_name}** promoted to **{selected_name}**!\nRoles assigned: {added_str}",
                ephemeral=True
            )

            try:
                await notify_channel.send(
                    f"🎉 {applicant.mention} Congratulations! Your application has been **approved**.\n"
                    f"You have been promoted to **{selected_name}**!"
                )
            except Exception:
                pass

    class RoleSelectView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.add_item(RoleSelect())

    await interaction.followup.send(
        f"Select the role to assign to **{applicant.display_name}**:",
        view=RoleSelectView(),
        ephemeral=True
    )

# ───────────────────────────────────────────
# PERSISTENT VIEWS (survive bot restart için custom_id kullanılır)
# ───────────────────────────────────────────

class ApplicationReviewView(discord.ui.View):
    """Fast pass / Transfer review view — Fastpass Team only."""

    def __init__(self, applicant_id: int, notify_channel_id: int):
        super().__init__(timeout=None)  # persistent
        self.applicant_id = applicant_id
        self.notify_channel_id = notify_channel_id

    @discord.ui.button(label="✅ Promote", style=discord.ButtonStyle.success, emoji="⬆️",
                       custom_id="app_promote")
    async def promote(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_fastpass_team(interaction):
            await interaction.response.send_message(
                "❌ Only **Fastpass Team** or **Foundership Team** can promote applicants.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)

        if not applicant:
            await interaction.followup.send("❌ Could not find the applicant in this server.", ephemeral=True)
            return

        await do_promote(interaction, applicant, notify_channel)

        # Butonları devre dışı bırak
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger, emoji="✖️",
                       custom_id="app_deny")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_fastpass_team(interaction):
            await interaction.response.send_message(
                "❌ Only **Fastpass Team** or **Foundership Team** can deny applications.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.followup.send(
            f"❌ Application from **{applicant.display_name if applicant else 'Unknown'}** has been **denied**."
        )

        if notify_channel and applicant:
            try:
                await notify_channel.send(
                    f"❌ {applicant.mention} Unfortunately, your application has been **denied**."
                )
            except Exception:
                pass


class PartnershipReviewView(discord.ui.View):
    """Partnership review view — Fastpass Team only."""

    def __init__(self, applicant_id: int, notify_channel_id: int, form_content: str):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.notify_channel_id = notify_channel_id
        self.form_content = form_content

    @discord.ui.button(label="✅ Approve & Post", style=discord.ButtonStyle.success, emoji="🤝",
                       custom_id="partner_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_fastpass_team(interaction):
            await interaction.response.send_message(
                "❌ Only **Fastpass Team** or **Foundership Team** can approve partnerships.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)
        partner_channel = interaction.guild.get_channel(PARTNERSHIP_CHANNEL_ID)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
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

        await interaction.followup.send(
            f"✅ Partnership approved and posted to {partner_channel.mention if partner_channel else '#partnerships'}!"
        )

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
        if not is_fastpass_team(interaction):
            await interaction.response.send_message(
                "❌ Only **Fastpass Team** or **Foundership Team** can deny partnerships.",
                ephemeral=True
            )
            return

        await interaction.response.defer()

        applicant = interaction.guild.get_member(self.applicant_id)
        notify_channel = interaction.guild.get_channel(self.notify_channel_id)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.followup.send(
            f"❌ Partnership from **{applicant.display_name if applicant else 'Unknown'}** denied."
        )

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
        name="🔒 Fastpass Team / Foundership Only",
        value="Promote/Deny/Approve buttons on submitted applications.",
        inline=False
    )
    embed.set_footer(text="LARP | Assistance • Los Angeles Roleplay")
    await ctx.send(embed=embed)

# ───────────────────────────────────────────
# s!fastpass
# ───────────────────────────────────────────

@bot.command(name="fastpass")
async def fastpass_command(ctx: commands.Context):
    applicant = ctx.author
    channel = ctx.channel

    def check_author(m):
        return m.author.id == applicant.id and m.channel.id == channel.id and \
               not m.content.startswith("!") and not m.content.startswith("s!")

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
        response_msg = await bot.wait_for("message", check=check_author, timeout=600)
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

    # Fastpass Team'e gönder
    fastpass_role = ctx.guild.get_role(FASTPASS_TEAM_ROLE_ID)
    fastpass_ping = fastpass_role.mention if fastpass_role else "@Fastpass Team"

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
    await ctx.send(f"{fastpass_ping} — New Fast Pass application!", embed=submission_embed, view=review_view)
    await ctx.send(
        f"✅ {applicant.mention} Your application has been submitted! "
        f"**Fastpass Team** has been notified and will review it shortly."
    )

# ───────────────────────────────────────────
# s!transfer
# ───────────────────────────────────────────

@bot.command(name="transfer")
async def transfer_command(ctx: commands.Context):
    applicant = ctx.author
    channel = ctx.channel

    def check_author(m):
        return m.author.id == applicant.id and m.channel.id == channel.id and \
               not m.content.startswith("!") and not m.content.startswith("s!")

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
        response_msg = await bot.wait_for("message", check=check_author, timeout=600)
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

    fastpass_role = ctx.guild.get_role(FASTPASS_TEAM_ROLE_ID)
    fastpass_ping = fastpass_role.mention if fastpass_role else "@Fastpass Team"

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
    await ctx.send(f"{fastpass_ping} — New Transfer/Retirement application!", embed=submission_embed, view=review_view)
    await ctx.send(
        f"✅ {applicant.mention} Your transfer application has been submitted! "
        f"**Fastpass Team** has been notified and will review it shortly."
    )

# ───────────────────────────────────────────
# s!partnership
# ───────────────────────────────────────────

@bot.command(name="partnership")
async def partnership_command(ctx: commands.Context):
    applicant = ctx.author
    channel = ctx.channel

    def check_author(m):
        return m.author.id == applicant.id and m.channel.id == channel.id and \
               not m.content.startswith("!") and not m.content.startswith("s!")

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
        "ℹ️ **Staff Partnership** = Cross-server staff fast pass (join their staff team)\n"
        "ℹ️ **Paying** = Paid/sponsored partnership"
    )

    try:
        response_msg = await bot.wait_for("message", check=check_author, timeout=600)
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

    fastpass_role = ctx.guild.get_role(FASTPASS_TEAM_ROLE_ID)
    fastpass_ping = fastpass_role.mention if fastpass_role else "@Fastpass Team"

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
    await ctx.send(f"{fastpass_ping} — New Partnership application!", embed=submission_embed, view=review_view)
    await ctx.send(
        f"✅ {applicant.mention} Your partnership application has been submitted! "
        f"**Fastpass Team** will review it shortly."
    )

# ───────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────

if __name__ == "__main__":
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
    print("🌐 HTTP health server started on port 10000")
    bot.run(DISCORD_TOKEN)
