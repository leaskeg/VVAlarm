import json
import logging
import os
from datetime import datetime, timedelta, timezone

import nextcord
import requests
from dotenv import load_dotenv
from nextcord.ext import commands, tasks

# Set up logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

# API tokens and other configurations
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
COC_API_TOKEN = os.getenv("COC_API_TOKEN")

if not DISCORD_BOT_TOKEN or not COC_API_TOKEN:
    raise ValueError(
        "Environment variables DISCORD_BOT_TOKEN and COC_API_TOKEN must be set."
    )

# File paths
LINKED_ACCOUNTS_FILE = "linked_accounts.json"
CLAN_CHANNELS_FILE = "clan_channels.json"
PREP_NOTIFICATION_FILE = "prep_notifications.json"
PREP_CHANNEL_FILE = "prep_channel.json"

# Global Variables
linked_accounts = {}
clan_channels = {}
prep_notifications = {}
prep_channel = None


# Utility Functions
def ensure_file_exists(filepath, default_data):
    if not os.path.exists(filepath):
        with open(filepath, "w") as file:
            json.dump(default_data, file)


def load_data(filepath):
    try:
        with open(filepath, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Error loading {filepath}: {e}")
        return {}


def save_data(filepath, data):
    with open(filepath, "w") as file:
        json.dump(data, file)


def load_prep_channel():
    if os.path.exists(PREP_CHANNEL_FILE):
        with open(PREP_CHANNEL_FILE, "r") as file:
            data = json.load(file)
            return data.get("prep_channel")
    return None


def save_prep_channel(channel_id):
    with open(PREP_CHANNEL_FILE, "w") as file:
        json.dump({"prep_channel": channel_id}, file)


# Initialize files
ensure_file_exists(LINKED_ACCOUNTS_FILE, {})
ensure_file_exists(CLAN_CHANNELS_FILE, {})
ensure_file_exists(PREP_NOTIFICATION_FILE, {})

prep_notifications = load_data(PREP_NOTIFICATION_FILE)
linked_accounts = load_data(LINKED_ACCOUNTS_FILE)
clan_channels = load_data(CLAN_CHANNELS_FILE)
prep_channel = load_prep_channel()


# Clash of Clans API utility functions
def make_coc_request(endpoint, retries=3):
    url = f"https://api.clashofclans.com/v1/{endpoint}"
    headers = {"Authorization": f"Bearer {COC_API_TOKEN}"}
    for attempt in range(retries):
        try:
            logging.info(f"Making API request to: {url}")
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Request error occurred: {e}")
            if attempt < retries - 1:
                continue
            break
    return None


def calculate_time_until_war_end(end_time_str):
    war_end_time = datetime.strptime(end_time_str, "%Y%m%dT%H%M%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    return war_end_time - datetime.now(timezone.utc)


def get_unattacked_players(war_data):
    return {
        member["tag"]: 2 - len(member.get("attacks", []))
        for member in war_data.get("clan", {}).get("members", [])
        if len(member.get("attacks", [])) < 2
    }


# Bot setup
intents = nextcord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


# Slash Command Groups
class ClashCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(
        name="link_account",
        description="Link en Clash of Clans konto til en Discord bruger (kun for administratorer)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def link_account(
        self,
        interaction: nextcord.Interaction,
        discord_user: nextcord.Member,
        player_tag: str,
    ):
        user_id = str(discord_user.id)
        if user_id not in linked_accounts:
            linked_accounts[user_id] = []
        if player_tag not in linked_accounts[user_id]:
            linked_accounts[user_id].append(player_tag)
            save_data(LINKED_ACCOUNTS_FILE, linked_accounts)
            await interaction.response.send_message(
                f"Linkede Clash of Clans tag {player_tag} til {discord_user.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Tag {player_tag} er allerede linket til {discord_user.mention}.",
                ephemeral=True,
            )

    @nextcord.slash_command(
        name="unlink_account",
        description="Fjern en Clash of Clans konto fra en Discord bruger (kun for administratorer)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def unlink_account(
        self,
        interaction: nextcord.Interaction,
        discord_user: nextcord.Member,
        player_tag: str,
    ):
        user_id = str(discord_user.id)
        if user_id in linked_accounts and player_tag in linked_accounts[user_id]:
            linked_accounts[user_id].remove(player_tag)
            if not linked_accounts[user_id]:
                del linked_accounts[user_id]
            save_data(LINKED_ACCOUNTS_FILE, linked_accounts)
            await interaction.response.send_message(
                f"Fjernede Clash of Clans tag {player_tag} fra {discord_user.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Kunne ikke finde tag {player_tag} for {discord_user.mention}.",
                ephemeral=True,
            )

    @nextcord.slash_command(
        name="set_reminder_channel",
        description="Vælg hvilken kanal der skal vise påmindelser",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def set_reminder_channel(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        global reminder_channel
        reminder_channel = channel.id
        await interaction.response.send_message(
            f"Påmindelseskanalen er sat til <#{reminder_channel}>.",
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="monitor_clan",
        description="Tilføj en klan til overvågning",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def monitor_clan(
        self, interaction: nextcord.Interaction, clan_name: str, clan_tag: str
    ):
        global reminder_channel
        if not reminder_channel:
            await interaction.response.send_message(
                "Ingen påmindelseskanal er blevet sat. Brug kommandoen '/set_reminder_channel' for at sætte en kanal.",
                ephemeral=True,
            )
            return

        if clan_tag in clan_channels:
            await interaction.response.send_message(
                f"Klanen {clan_name} ({clan_tag}) overvåges allerede.",
                ephemeral=True,
            )
        else:
            clan_channels[clan_tag] = {"name": clan_name, "channel": reminder_channel}
            save_data(CLAN_CHANNELS_FILE, clan_channels)
            await interaction.response.send_message(
                f"Klanen {clan_name} ({clan_tag}) er nu tilføjet til overvågning.",
                ephemeral=True,
            )

    @nextcord.slash_command(
        name="set_prep_channel",
        description="Sæt kanalen til forberedelses-påmindelser (Kun for administratorer)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def set_prep_channel(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        global prep_channel
        prep_channel = channel.id
        save_prep_channel(prep_channel)
        await interaction.response.send_message(
            f"Forberedelses-påmindelseskanalen er sat til <#{prep_channel}>.",
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="assign_prep_notifiers",
        description="Tildel brugere til at modtage forberedelses-påmindelser (Kun for administratorer)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def assign_prep_notifiers(
        self,
        interaction: nextcord.Interaction,
        clan: str,
        users: nextcord.Member,
    ):
        global prep_channel
        if not prep_channel:
            await interaction.response.send_message(
                "Ingen forberedelseskanal er blevet sat. Brug kommandoen '/set_prep_channel' for at sætte en kanal.",
                ephemeral=True,
            )
            return

        clan_tag = None
        for tag, info in clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.response.send_message(
                f"Klanen '{clan}' blev ikke fundet i overvågningen.",
                ephemeral=True,
            )
            return

        user_ids = []
        user_ids.append(users.id)

        if clan_tag not in prep_notifications:
            prep_notifications[clan_tag] = {"channel": prep_channel, "notifiers": []}

        already_assigned = []
        newly_assigned = []

        for user_id in user_ids:
            if user_id in prep_notifications[clan_tag]["notifiers"]:
                already_assigned.append(f"<@{user_id}>")
            else:
                prep_notifications[clan_tag]["notifiers"].append(user_id)
                newly_assigned.append(f"<@{user_id}>")

        save_data(PREP_NOTIFICATION_FILE, prep_notifications)

        response_message = ""
        if newly_assigned:
            response_message += f"Følgende brugere er nu tildelt til at modtage forberedelses-påmindelser for klan '{clan}': {', '.join(newly_assigned)}.\n"
        if already_assigned:
            response_message += (
                f"Følgende brugere var allerede tildelt: {', '.join(already_assigned)}."
            )

        await interaction.response.send_message(response_message)

    @assign_prep_notifiers.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        matching_clans = [
            info["name"]
            for tag, info in clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])

    @nextcord.slash_command(
        name="match_status", description="Tjek status for klanens krig."
    )
    async def match_status(self, interaction: nextcord.Interaction, clan: str):
        await interaction.response.defer()  # Defer the response to allow follow-up messages
        clan_tag = None
        for tag, info in clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.followup.send(
                f"Klanen {clan} blev ikke fundet.", ephemeral=True
            )
            return

        war_data = make_coc_request(f"clans/{clan_tag.replace('#', '%23')}/currentwar")
        if not war_data:
            await interaction.followup.send(
                f"Kunne ikke hente data for klan {clan} ({clan_tag}).",
                ephemeral=True,
            )
            return

        state = war_data.get("state", "unknown")

        def split_message(message, limit=2000):
            """Split a message into chunks of a specified character limit."""
            return [message[i : i + limit] for i in range(0, len(message), limit)]

        if state == "warEnded":
            unattacked_players = get_unattacked_players(war_data)
            if unattacked_players:
                message = f"⚔️ Klan {clan} ({clan_tag}) har afsluttet krigen.\n"
                message += "Følgende spillere brugte ikke alle deres angreb:\n"

                for player_tag, missing_attacks in unattacked_players.items():
                    discord_mentions = [
                        f"<@{user_id}>"
                        for user_id, tags in linked_accounts.items()
                        if player_tag in tags
                    ]
                    linked_users = (
                        ", ".join(discord_mentions)
                        if discord_mentions
                        else "Ingen Discord-link"
                    )
                    message += f"- {player_tag}: Mangler {missing_attacks} angreb. Linket: {linked_users}\n"
            else:
                message = f"⚔️ Klan {clan} ({clan_tag}) har afsluttet krigen.\nAlle spillere brugte deres angreb! 💪"

            messages = split_message(message)
            for msg in messages:
                await interaction.followup.send(msg)

        elif state == "preparation":
            war_end_time_str = war_data.get("endTime")
            time_until_start = calculate_time_until_war_end(war_end_time_str)
            time_until_start_formatted = f"{time_until_start.seconds // 3600} timer, {(time_until_start.seconds // 60) % 60} minutter"
            await interaction.followup.send(
                f"Klan {clan} ({clan_tag}) er i forberedelsesfasen. Krigen starter om: {time_until_start_formatted}."
            )

        elif state == "inWar":
            war_end_time_str = war_data.get("endTime")
            time_until_end = calculate_time_until_war_end(war_end_time_str)
            time_until_end_formatted = f"{time_until_end.seconds // 3600} timer, {(time_until_end.seconds // 60) % 60} minutter"

            unattacked_players = get_unattacked_players(war_data)
            message = f"⚔️ Klan {clan} ({clan_tag}) er i krig!⏰ Tid tilbage: {time_until_end_formatted}\n"

            if unattacked_players:
                message += "Spillere der mangler at angribe:\n"
                for player_tag, missing_attacks in unattacked_players.items():
                    discord_mentions = [
                        f"<@{user_id}>"
                        for user_id, tags in linked_accounts.items()
                        if player_tag in tags
                    ]
                    linked_users = (
                        ", ".join(discord_mentions)
                        if discord_mentions
                        else "Ingen Discord-link"
                    )
                    message += f"- {player_tag}: Mangler {missing_attacks} angreb. Linket: {linked_users}\n"
            else:
                message += "Alle spillere har angrebet! 💪"

            messages = split_message(message)
            for msg in messages:
                await interaction.followup.send(msg)

        else:
            await interaction.followup.send(
                f"Klan {clan} ({clan_tag}) er i en ukendt tilstand: {state}",
                ephemeral=True,
            )

    @match_status.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        matching_clans = [
            info["name"]
            for tag, info in clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])

    @nextcord.slash_command(
        name="unlinked_accounts",
        description="Vis hvilke konti der ikke er linket til Discord i en overvåget klan (Kun for administratorer)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def unlinked_accounts(self, interaction: nextcord.Interaction, clan: str):
        clan_tag = None
        for tag, info in clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.response.send_message(
                f"Klanen '{clan}' blev ikke fundet i overvågningen.", ephemeral=True
            )
            return

        war_data = make_coc_request(f"clans/{clan_tag.replace('#', '%23')}/currentwar")
        if not war_data:
            await interaction.response.send_message(
                f"Kunne ikke hente data for klan '{clan}' ({clan_tag}).", ephemeral=True
            )
            return

        unlinked_players = []
        for member in war_data.get("clan", {}).get("members", []):
            if all(member["tag"] not in tags for tags in linked_accounts.values()):
                unlinked_players.append(f"{member['name']} ({member['tag']})")

        if unlinked_players:
            message = (
                f"⚠️ Følgende konti i klan '{clan}' ({clan_tag}) er ikke linket til Discord:\n"
                + "\n".join(unlinked_players)
            )
        else:
            message = (
                f"✅ Alle konti i klan '{clan}' ({clan_tag}) er linket til Discord!"
            )

        await interaction.response.send_message(message[:2000])

    @unlinked_accounts.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        matching_clans = [
            info["name"]
            for tag, info in clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])


# Cog Registration
bot.add_cog(ClashCommands(bot))


# Background Tasks
@tasks.loop(minutes=1)
async def reminder_check():
    for clan_tag, channel_data in clan_channels.items():
        logging.info(f"Checking reminder for clan: {clan_tag}")

        war_data = make_coc_request(f"clans/{clan_tag.replace('#', '%23')}/currentwar")
        if not war_data:
            logging.warning(f"No war data for clan: {clan_tag}")
            continue

        if war_data.get("state") != "inWar":
            logging.info(f"Clan {clan_tag} is not in war state.")
            continue

        war_end_time_str = war_data.get("endTime")
        time_until_end = calculate_time_until_war_end(war_end_time_str)
        logging.info(f"Time until war ends for clan {clan_tag}: {time_until_end}")

        reminder_time_messages = {
            "1_hour": "⏰ Der er 1 time tilbage af krigen! Husk at angribe! ⏰",
            "30_min": "⏰ Der er 30 minutter tilbage af krigen! Angrib, IDAG TAK! ⏰",
            "15_min": "⚠️ Så er der 15 minutter tilbage af krigen! Angrib nu dit fedtnæb! ⚠️",
        }

        reminder_triggered = None
        if timedelta(hours=1) >= time_until_end > timedelta(minutes=59):
            reminder_triggered = "1_hour"
        elif timedelta(minutes=30) >= time_until_end > timedelta(minutes=29):
            reminder_triggered = "30_min"
        elif timedelta(minutes=15) >= time_until_end > timedelta(minutes=14):
            reminder_triggered = "15_min"

        if reminder_triggered:
            message = reminder_time_messages[reminder_triggered]
            clan_name = channel_data.get(
                "name", "Ukendt Klan"
            )  # Fallback if name is missing
            unattacked_players = get_unattacked_players(war_data)
            channel = bot.get_channel(channel_data["channel"])
            if channel:
                player_list = "\n".join(
                    f"- {player_tag}: Mangler {missing_attacks} angreb. "
                    f"Linket: {', '.join([f'<@{user_id}>' for user_id, tags in linked_accounts.items() if player_tag in tags]) or 'Ingen Discord-link'}"
                    for player_tag, missing_attacks in unattacked_players.items()
                )
                try:
                    await channel.send(
                        f"⚠️ Påmindelse om krig for klan {clan_name} ({clan_tag}) ⚠️\n{message}\n\nSpillere der mangler at angribe:\n{player_list}"
                    )
                    logging.info(
                        f"Sent reminder for clan {clan_name} ({clan_tag}) to channel {channel_data['channel']}"
                    )
                except Exception as e:
                    logging.error(
                        f"Failed to send message to channel {channel_data['channel']} for clan {clan_tag}: {e}"
                    )


@tasks.loop(minutes=1)
async def prep_notification_check():
    for clan_tag, prep_data in prep_notifications.items():
        logging.info(f"Checking preparation status for clan: {clan_tag}")
        war_data = make_coc_request(f"clans/{clan_tag.replace('#', '%23')}/currentwar")
        if not war_data:
            logging.warning(f"No war data for clan: {clan_tag}")
            continue

        if war_data.get("state") != "preparation":
            logging.info(f"Clan {clan_tag} is not in preparation state.")
            continue

        war_end_time_str = war_data.get("endTime")
        time_until_start = calculate_time_until_war_end(war_end_time_str)

        if timedelta(hours=1) >= time_until_start > timedelta(minutes=59):
            if prep_data.get("1_hour_reminder_sent"):
                logging.info(
                    f"1-hour reminder already sent for clan: {clan_tag}. Skipping reminder."
                )
                continue

            prep_channel_id = prep_data.get("channel", prep_channel)
            notifiers = prep_data.get("notifiers", [])
            channel = bot.get_channel(prep_channel_id)

            if channel and notifiers:
                notifier_mentions = ", ".join(
                    [f"<@{user_id}>" for user_id in notifiers]
                )
                try:
                    await channel.send(
                        f"⚠️ Forberedelses-påmindelse for klan {clan_tag}:\n"
                        f"{notifier_mentions}, der er mindre end 1 time tilbage før krigen starter!"
                    )
                    logging.info(
                        f"Sent preparation reminder for clan {clan_tag} to channel {prep_channel_id}."
                    )

                    prep_data["1_hour_reminder_sent"] = True
                    save_data(PREP_NOTIFICATION_FILE, prep_notifications)

                except Exception as e:
                    logging.error(
                        f"Failed to send message to channel {prep_channel_id} for clan {clan_tag}: {e}"
                    )
            else:
                logging.warning(
                    f"Channel {prep_channel_id} or notifiers missing for clan {clan_tag}."
                )


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    await bot.sync_all_application_commands()
    print("Slash commands synced globally!")
    reminder_check.start()
    prep_notification_check.start()


bot.run(DISCORD_BOT_TOKEN)
