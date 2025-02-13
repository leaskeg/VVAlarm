# region Imports and Configuration
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import nextcord
import requests
from dotenv import load_dotenv
from nextcord.ext import commands, tasks
import aiohttp
import asyncio
from asyncio import Semaphore

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
API_SEMAPHORE = Semaphore(5)
# Global Variables
linked_accounts = {}
clan_channels = {}
prep_notifications = {}
prep_channel = None
reminder_channel = None
# endregion


# region File Management Functions
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


# endregion

# region File Initialization
# Initialize files
ensure_file_exists(LINKED_ACCOUNTS_FILE, {})
ensure_file_exists(CLAN_CHANNELS_FILE, {})
ensure_file_exists(PREP_NOTIFICATION_FILE, {})

prep_notifications = load_data(PREP_NOTIFICATION_FILE)
linked_accounts = load_data(LINKED_ACCOUNTS_FILE)
clan_channels = load_data(CLAN_CHANNELS_FILE)
prep_channel = load_prep_channel()
# endregion


# region API Functions
async def make_coc_request_async(endpoint, retries=3):
    """Asynchronous version of make_coc_request using aiohttp with rate limiting"""
    async with API_SEMAPHORE:
        url = f"https://api.clashofclans.com/v1/{endpoint}"
        headers = {"Authorization": f"Bearer {COC_API_TOKEN}"}

        for attempt in range(retries):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        if response.status == 404:
                            logging.warning(f"404 Not Found: {url}")
                            return None
                        response.raise_for_status()
                        return await response.json()
            except Exception as e:
                if attempt == retries - 1:
                    logging.error(
                        f"Failed to make request after {retries} attempts: {e}"
                    )
                    return None
                await asyncio.sleep(1)
        return None


def calculate_time_until_war_end(end_time_str, state):
    try:
        logging.info(f"Raw endTime from API: {end_time_str}")
        war_end_time = datetime.strptime(end_time_str, "%Y%m%dT%H%M%S.%fZ").replace(
            tzinfo=timezone.utc
        )

        # Adjust endTime for preparation phase
        if state == "preparation":
            logging.info(
                "Adjusting endTime for preparation phase (subtracting 24 hours)"
            )
            war_end_time -= timedelta(hours=24)

        current_time = datetime.now(timezone.utc)
        time_until_end = war_end_time - current_time

        # Format for logging in a cleaner way
        hours = int(time_until_end.total_seconds() // 3600)
        minutes = int((time_until_end.total_seconds() % 3600) // 60)
        logging.info(f"Time until end: {hours} hours and {minutes} minutes")

        return time_until_end
    except ValueError as e:
        logging.error(f"Error parsing endTime: {e}")
        return timedelta(0)  # Default to 0 if parsing fails


def get_unattacked_players(war_data, is_cwl=False):
    # If CWL, each player has 1 attack. Otherwise, it's 2 attacks for normal wars.
    max_attacks = 1 if is_cwl else 2

    return {
        member["tag"]: max_attacks - len(member.get("attacks", []))
        for member in war_data.get("clan", {}).get("members", [])
        if len(member.get("attacks", [])) < max_attacks
    }


async def get_league_group_data(clan_tag):
    endpoint = f"clans/{clan_tag.replace('#', '%23')}/currentwar/leaguegroup"
    return await make_coc_request_async(endpoint)


# endregion

# region Bot Setup
intents = nextcord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
# endregion


# region Clash Commands Class
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
        name="check_prep_config",
        description="Check preparation notification configuration",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def check_prep_config(self, interaction: nextcord.Interaction):
        await interaction.response.defer(ephemeral=True)
        message = "Current Preparation Configuration:\n\n"

        message += f"Global Prep Channel: {prep_channel}\n\n"

        message += "Clan Configurations:\n"
        for clan_tag, data in prep_notifications.items():
            message += f"\nClan {clan_tag}:\n"
            message += f"Channel: {data.get('channel')}\n"
            message += f"Notifiers: {', '.join([f'<@{uid}>' for uid in data.get('notifiers', [])])}\n"
            message += f"Wars tracked: {len(data.get('wars', {}))}\n"

        await interaction.followup.send(message, ephemeral=True)

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
        await interaction.response.defer()
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

        league_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}/currentwar/leaguegroup"
        )

        if league_data:
            league_state = league_data.get("state", "unknown")
            logging.info(f"CWL state for {clan}: {league_state}")

            if league_state == "inWar":
                for round_num, round_data in enumerate(league_data.get("rounds", [])):
                    for war_tag in round_data.get("warTags", []):
                        if war_tag == "#0":
                            continue

                        war_data = await make_coc_request_async(
                            f"clanwarleagues/wars/{war_tag.replace('#', '%23')}"
                        )
                        if not war_data:
                            continue

                        if (
                            war_data["clan"]["tag"] == clan_tag
                            or war_data["opponent"]["tag"] == clan_tag
                        ):
                            state = war_data.get("state", "unknown")
                            if state == "inWar":
                                await self.process_war_status(
                                    interaction,
                                    clan,
                                    clan_tag,
                                    war_data,
                                    state,
                                    is_cwl=True,
                                    round_num=round_num + 1,
                                )
                                return

            elif league_state == "preparation":
                await interaction.followup.send(
                    f"⚔️ CWL for {clan} ({clan_tag}) er i forberedelsesfasen.",
                    ephemeral=True,
                )
                return

        war_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}/currentwar"
        )
        if war_data and war_data.get("state") == "inWar":
            await self.process_war_status(
                interaction, clan, clan_tag, war_data, "inWar", is_cwl=False
            )
        else:
            await interaction.followup.send(
                f"Klanen {clan} er ikke i nogen aktive krige.", ephemeral=True
            )

    async def process_war_status(
        self, interaction, clan, clan_tag, war_data, state, is_cwl=False, round_num=None
    ):
        def split_message(message, limit=2000):
            return [message[i : i + limit] for i in range(0, len(message), limit)]

        war_type = "CWL" if is_cwl else "Normal"
        round_info = f" (Runde {round_num})" if is_cwl else ""

        clan_data = (
            war_data["clan"]
            if war_data["clan"]["tag"] == clan_tag
            else war_data["opponent"]
        )
        opponent_data = (
            war_data["opponent"]
            if war_data["clan"]["tag"] == clan_tag
            else war_data["clan"]
        )

        clan_name = clan_data.get("name", "Unknown")
        opponent_name = opponent_data.get("name", "Unknown")
        stars_clan = clan_data.get("stars", 0)
        stars_opponent = opponent_data.get("stars", 0)
        destruction_clan = clan_data.get("destructionPercentage", 0)
        destruction_opponent = opponent_data.get("destructionPercentage", 0)

        war_end_time_str = war_data.get("endTime")
        time_until_end = calculate_time_until_war_end(war_end_time_str, "inWar")
        time_until_end_formatted = f"{time_until_end.seconds // 3600} timer, {(time_until_end.seconds // 60) % 60} minutter"

        unattacked_players = {
            member["tag"]: 1 if is_cwl else 2 - len(member.get("attacks", []))
            for member in clan_data.get("members", [])
            if len(member.get("attacks", [])) < (1 if is_cwl else 2)
        }

        message = (
            f"⚔️ {war_type} krig{round_info} for {clan} ({clan_tag}) mod {opponent_name}\n"
            f"⏰ Tid tilbage: {time_until_end_formatted}\n\n"
            f"Stillingen:\n"
            f"\n"
            f"{clan_name}:\n"
            f"⭐ {stars_clan} | {destruction_clan:.2f}%\n\n"
            f"{opponent_name}:\n"
            f"⭐ {stars_opponent} | {destruction_opponent:.2f}%\n"
        )

        player_list = ""
        if unattacked_players:
            player_list = "\nSpillere der mangler at angribe:\n"
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
                player_list += f"- {player_tag}: Mangler {missing_attacks} angreb. Linket: {linked_users}\n"
        else:
            player_list = "\nAlle spillere har angrebet! 💪"

        message += player_list

        messages = split_message(message)
        for msg in messages:
            await interaction.followup.send(msg)

    @match_status.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        try:
            # Get all clan names from clan_channels
            clan_names = [info["name"] for tag, info in clan_channels.items()]

            if not query:  # If no query, return all clans (up to 25)
                await interaction.response.send_autocomplete(clan_names[:25])
                return

            # Filter clan names based on query
            matching_clans = [
                name for name in clan_names if query.lower() in name.lower()
            ][
                :25
            ]  # Limit to 25 results

            await interaction.response.send_autocomplete(matching_clans)

        except Exception as e:
            logging.error(f"Error in clan_autocomplete: {str(e)}")
            await interaction.response.send_autocomplete([])

    @nextcord.slash_command(
        name="cwl_leaderboard",
        description="Vis CWL leaderboard for den aktuelle sæson.",
    )
    async def cwl_leaderboard(self, interaction: nextcord.Interaction, clan: str):
        await interaction.response.defer()

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

        league_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}/currentwar/leaguegroup"
        )
        if not league_data:
            await interaction.followup.send(
                "Kunne ikke hente CWL data.", ephemeral=True
            )
            return

        leaderboard = {
            cwl_clan["tag"]: {
                "name": cwl_clan["name"],
                "stars": 0,
                "destruction": 0,
                "matches": 0,
            }
            for cwl_clan in league_data.get("clans", [])
        }

        for round_data in league_data.get("rounds", []):
            for war_tag in round_data.get("warTags", []):
                if war_tag == "#0":
                    continue

                war_data = await make_coc_request_async(
                    f"clanwarleagues/wars/{war_tag.replace('#', '%23')}"
                )
                if not war_data:
                    continue

                clan_stars = war_data["clan"].get("stars", 0)
                opponent_stars = war_data["opponent"].get("stars", 0)
                clan_percentage = war_data["clan"].get("destructionPercentage", 0)
                opponent_percentage = war_data["opponent"].get(
                    "destructionPercentage", 0
                )
                clan_tag_in_war = war_data["clan"]["tag"]
                opponent_tag_in_war = war_data["opponent"]["tag"]

                if clan_tag_in_war in leaderboard:
                    leaderboard[clan_tag_in_war]["stars"] += clan_stars
                    leaderboard[clan_tag_in_war]["destruction"] += clan_percentage
                    leaderboard[clan_tag_in_war]["matches"] += 1

                if opponent_tag_in_war in leaderboard:
                    leaderboard[opponent_tag_in_war]["stars"] += opponent_stars
                    leaderboard[opponent_tag_in_war][
                        "destruction"
                    ] += opponent_percentage
                    leaderboard[opponent_tag_in_war]["matches"] += 1

        for entry in leaderboard.values():
            if entry["matches"] > 0:
                entry["destruction"] /= entry["matches"]

        sorted_leaderboard = sorted(
            leaderboard.values(), key=lambda x: (-x["stars"], -x["destruction"])
        )

        message = (
            f"📊 **CWL Leaderboard for {league_data.get('season', 'Unknown')}**\n"
            f"**Klan: {clan} ({clan_tag})**\n\n"
        )

        for rank, entry in enumerate(sorted_leaderboard, start=1):
            message += f"**{rank}. {entry['name']}**Stars: **{entry['stars']}** ⭐ | Destruction: **{entry['destruction']:.2f}%** 💥 \n"

        await interaction.followup.send(message.strip())

    @cwl_leaderboard.on_autocomplete("clan")
    async def cwl_leaderboard_autocomplete(
        self, interaction: nextcord.Interaction, query: str
    ):
        matching_clans = [
            info["name"]
            for tag, info in clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])

    @nextcord.slash_command(
        name="reset_prep_reminder",
        description="Reset the preparation reminder status for testing",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def reset_prep_reminder(
        self, interaction: nextcord.Interaction, clan_tag: str
    ):
        """Reset the preparation reminder status for a clan."""
        if not clan_tag.startswith("#"):
            clan_tag = f"#{clan_tag}"

        if clan_tag in prep_notifications:
            war_id = f"cwl_prep_{datetime.now(timezone.utc).strftime('%Y-%m')}"
            if (
                "wars" in prep_notifications[clan_tag]
                and war_id in prep_notifications[clan_tag]["wars"]
            ):
                prep_notifications[clan_tag]["wars"][war_id][
                    "1_hour_reminder_sent"
                ] = False
                save_data(PREP_NOTIFICATION_FILE, prep_notifications)
                await interaction.response.send_message(
                    f"Reset reminder status for clan {clan_tag}", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"No active war found for clan {clan_tag}", ephemeral=True
                )
        else:
            await interaction.response.send_message(
                f"Clan {clan_tag} not found in notifications", ephemeral=True
            )

    @nextcord.slash_command(
        name="unlinked_accounts",
        description="Vis hvilke konti der ikke er linket til Discord i en overvåget klan (Kun for administratorer)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def unlinked_accounts(self, interaction: nextcord.Interaction, clan: str):
        await interaction.response.defer()

        clan_tag = None
        for tag, info in clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.followup.send(
                f"Klanen '{clan}' blev ikke fundet i overvågningen.", ephemeral=True
            )
            return

        clan_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}"
        )
        if not clan_data:
            await interaction.followup.send(
                f"Kunne ikke hente data for klan '{clan}' ({clan_tag}).", ephemeral=True
            )
            return

        all_linked_tags = [tag for tags in linked_accounts.values() for tag in tags]

        unlinked_players = []
        for member in clan_data.get("memberList", []):
            player_tag = member.get("tag")
            if player_tag and player_tag not in all_linked_tags:
                player_name = member.get("name", "Unknown")
                raw_role = member.get("role", "member")
                role_mapping = {
                    "member": "member",
                    "admin": "elder",
                    "coLeader": "coLeader",
                    "leader": "leader",
                }
                player_role = role_mapping.get(raw_role, "member")
                player_th = member.get("townHallLevel", "?")
                unlinked_players.append(
                    f"• {player_name} (TH{player_th}, {player_role}) - {player_tag}"
                )

        if unlinked_players:
            message = (
                f"⚠️ Følgende konti i klan '{clan}' ({clan_tag}) er ikke linket til Discord:\n\n"
                + "\n".join(unlinked_players)
                + f"\n\nTotal: {len(unlinked_players)} ulinket konti"
            )
        else:
            message = (
                f"✅ Alle konti i klan '{clan}' ({clan_tag}) er linket til Discord!"
            )

        if len(message) > 2000:
            chunks = []
            current_chunk = f"⚠️ Ulinket konti i klan '{clan}' ({clan_tag}):\n\n"

            for player in unlinked_players:
                if len(current_chunk) + len(player) + 2 > 1900:
                    chunks.append(current_chunk)
                    current_chunk = f"⚠️ Fortsat - unlinket konti:\n\n{player}\n"
                else:
                    current_chunk += player + "\n"

            if current_chunk:
                chunks.append(current_chunk)

            chunks[-1] += f"\nTotal: {len(unlinked_players)} ulinket konti"

            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(chunk)
                else:
                    await interaction.followup.send(chunk)
        else:
            await interaction.followup.send(message)

    @unlinked_accounts.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        matching_clans = [
            info["name"]
            for tag, info in clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])


def setup():
    bot.add_cog(ClashCommands(bot))


# endregion


# region Reminder Functions
@tasks.loop(minutes=1)
async def reminder_check():
    try:
        logging.info("\n=== Starting reminder check cycle ===")

        # Run checks sequentially instead of concurrently to avoid duplicate logs
        for clan_tag, channel_data in clan_channels.items():
            # Check CWL status
            logging.info(f"\n🔍 Checking clan {clan_tag}:")

            # 1. Check CWL status
            logging.info("  ↳ Checking CWL status")
            league_data = await make_coc_request_async(
                f"clans/{clan_tag.replace('#', '%23')}/currentwar/leaguegroup"
            )
            if league_data and league_data.get("state") == "inWar":
                await cwl_reminder_check_for_clan(clan_tag, channel_data)

            # 2. Check normal war status
            logging.info("  ↳ Checking normal war status")
            war_data = await make_coc_request_async(
                f"clans/{clan_tag.replace('#', '%23')}/currentwar"
            )
            if war_data and war_data.get("state") == "inWar":
                await trigger_reminders(war_data, channel_data, is_cwl=False)

            # 3. Check preparation status
            logging.info("  ↳ Checking preparation status")
            if clan_tag in prep_notifications:
                await check_prep_status(clan_tag, war_data, league_data)

        logging.info("=== Completed reminder check cycle ===\n")

    except Exception as e:
        logging.error(f"Error in reminder check: {e}")


# endregion


# region War Reminder Checks
async def normal_war_reminder_check():
    for clan_tag, channel_data in clan_channels.items():
        logging.info(
            f"🔍 Checking for in-war attack reminders (Normal War) - Clan: {clan_tag}"
        )

        war_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}/currentwar"
        )
        if not war_data or war_data.get("state") != "inWar":
            continue

        await trigger_reminders(war_data, channel_data, is_cwl=False)


# endregion


# region Reminder Utilities
def reset_reminder_flags(clan_tag, war_id):
    """Reset reminder flags for a given war ID in the prep_notifications."""
    if (
        clan_tag in prep_notifications
        and war_id in prep_notifications[clan_tag]["wars"]
    ):
        logging.info(f"Resetting reminder flags for clan {clan_tag}, War ID: {war_id}")
        prep_notifications[clan_tag]["wars"][war_id]["1_hour_reminder_sent"] = False
        save_data(PREP_NOTIFICATION_FILE, prep_notifications)


async def trigger_reminders(war_data, channel_data, is_cwl=False, round_num=None):
    war_end_time_str = war_data.get("endTime")
    time_until_end = calculate_time_until_war_end(war_end_time_str, "inWar")

    war_type = "CWL" if is_cwl else "Normal"
    round_info = f" (Runde {round_num})" if is_cwl and round_num else ""

    reminder_time_messages = {
        "1_hour": {
            "normal": "⏰ Der er 1 time tilbage af krigen! Husk at angribe! ⏰",
            "cwl": "⏰ Der er 1 time tilbage af krigen! Husk at angribe og fylde CC til næste kamp! ⏰",
        },
        "30_min": {
            "normal": "⏰ Der er 30 minutter tilbage af krigen! Angrib nu! ⏰",
            "cwl": "⏰ Der er 30 minutter tilbage af krigen! Angrib nu og husk at fylde CC til næste kamp! ⏰",
        },
        "15_min": {
            "normal": "⚠️ 15 minutter tilbage af krigen! Skynd dig at angribe! ⚠️",
            "cwl": "⚠️ 15 minutter tilbage af krigen! SÅ ER DET ALTSÅ NU FEDTNÆB! - Husk også at fylde CC til næste kamp! ⚠️",
        },
    }

    reminder_triggered = None
    if timedelta(hours=1) >= time_until_end > timedelta(minutes=59):
        reminder_triggered = "1_hour"
    elif timedelta(minutes=30) >= time_until_end > timedelta(minutes=29):
        reminder_triggered = "30_min"
    elif timedelta(minutes=15) >= time_until_end > timedelta(minutes=14):
        reminder_triggered = "15_min"

    if reminder_triggered:
        channel = bot.get_channel(channel_data["channel"])
        if not channel:
            logging.error(f"Could not find channel for clan {channel_data}")
            return

        clan_name = war_data["clan"].get("name", "Unknown")
        clan_tag = war_data["clan"].get("tag", "Unknown")
        unattacked_players = get_unattacked_players(war_data, is_cwl=is_cwl)

        # Only send message if there are unattacked players
        if not unattacked_players:
            logging.info(
                f"All players have attacked in {war_type} war for clan {clan_tag}"
            )
            return

        message_type = "cwl" if is_cwl else "normal"
        reminder_message = reminder_time_messages[reminder_triggered][message_type]

        message = (
            f"⚔️ {war_type} krig{round_info} for {clan_name} ({clan_tag})\n"
            f"{reminder_message}\n\n"
            "Spillere der mangler at angribe:\n"
        )

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

        try:
            await channel.send(message)
            logging.info(
                f"Sent {reminder_triggered} reminder for {war_type} war to {channel_data['channel']}"
            )
        except Exception as e:
            logging.error(f"Failed to send reminder: {e}")


async def cwl_reminder_check_for_clan(clan_tag, channel_data):
    """Helper function to check CWL status for a single clan"""
    league_group = await make_coc_request_async(
        f"clans/{clan_tag.replace('#', '%23')}/currentwar/leaguegroup"
    )

    if not league_group or league_group.get("state") != "inWar":
        return

    current_war = None
    current_round = None

    for round_idx, round_data in enumerate(league_group.get("rounds", [])):
        for war_tag in round_data.get("warTags", []):
            if war_tag == "#0":
                continue

            war_data = await make_coc_request_async(
                f"clanwarleagues/wars/{war_tag.replace('#', '%23')}"
            )

            if (
                war_data
                and war_data.get("state") == "inWar"
                and (
                    war_data["clan"]["tag"] == clan_tag
                    or war_data["opponent"]["tag"] == clan_tag
                )
            ):
                current_war = war_data
                current_round = round_idx + 1

                if war_data["clan"]["tag"] != clan_tag:
                    current_war["clan"], current_war["opponent"] = (
                        current_war["opponent"],
                        current_war["clan"],
                    )

                await trigger_reminders(
                    current_war, channel_data, is_cwl=True, round_num=current_round
                )
                break

        if current_war:
            break


async def check_prep_status(clan_tag, war_data, league_data):
    """Helper function to check preparation status for a single clan"""
    if clan_tag not in prep_notifications:
        return

    prep_data = prep_notifications[clan_tag]

    # Check normal war preparation
    if war_data:
        war_state = war_data.get("state")

        if war_state == "inWar":
            logging.info(
                f"Clan {clan_tag} is now in war. Resetting prep notifications."
            )
            prep_data["wars"] = {}
        elif war_state == "preparation":
            await process_normal_war_prep(clan_tag, war_data, prep_data)

    # Check CWL preparation
    if league_data and league_data.get("state") == "preparation":
        clan_name = next(
            (
                clan.get("name")
                for clan in league_data.get("clans", [])
                if clan.get("tag") == clan_tag
            ),
            None,
        )

        if clan_name:
            war_id = f"cwl_prep_{datetime.now(timezone.utc).strftime('%Y-%m')}"

            # Ensure war data structure exists
            if "wars" not in prep_data:
                prep_data["wars"] = {}
            if war_id not in prep_data["wars"]:
                prep_data["wars"][war_id] = {"1_hour_reminder_sent": False}

            # Get first war tag
            war_tag = next(
                (
                    tag
                    for round_data in league_data.get("rounds", [])
                    for tag in round_data.get("warTags", [])
                    if tag != "#0"
                ),
                None,
            )

            if war_tag:
                war_data = await make_coc_request_async(
                    f"clanwarleagues/wars/{war_tag.replace('#', '%23')}"
                )
                if war_data:
                    try:
                        prep_end_time = datetime.strptime(
                            war_data["startTime"], "%Y%m%dT%H%M%S.%fZ"
                        ).replace(tzinfo=timezone.utc)
                        current_time = datetime.now(timezone.utc)
                        time_until_prep_end = prep_end_time - current_time

                        reminder_sent = prep_data["wars"][war_id].get(
                            "1_hour_reminder_sent", False
                        )
                        should_send = (
                            timedelta(minutes=60)
                            >= time_until_prep_end
                            > timedelta(minutes=55)
                        )

                        if should_send and not reminder_sent:
                            prep_channel_id = prep_data.get("channel", prep_channel)
                            notifiers = prep_data.get("notifiers", [])

                            if prep_channel_id and notifiers:
                                channel = bot.get_channel(prep_channel_id)
                                if channel:
                                    notifier_mentions = ", ".join(
                                        [f"<@{user_id}>" for user_id in notifiers]
                                    )
                                    message = (
                                        f"🎯 **CWL Forberedelses-påmindelse for {clan_name}** ({clan_tag})\n\n"
                                        f"> 🔔 **Opmærksomhed:** {notifier_mentions}\n"
                                        f"> ⏳ **Tid tilbage:** Mindre end 1 time tilbage af forberedelsesfasen!\n\n"
                                        f"⚔️ **Husk at sætte CWL lineup og tjek CC! 🏆**\n"
                                        f"Sørg for, at alt er klar til kamp - flæk flæk! 💪🚀"
                                    )

                                    await channel.send(message)
                                    logging.info(
                                        f"Successfully sent CWL prep reminder for clan {clan_tag}"
                                    )

                                    prep_data["wars"][war_id][
                                        "1_hour_reminder_sent"
                                    ] = True
                                    save_data(
                                        PREP_NOTIFICATION_FILE, prep_notifications
                                    )
                    except Exception as e:
                        logging.error(f"Error processing CWL prep reminder: {str(e)}")


# endregion


# region Preparation Notifications
def ensure_war_data_exists(clan_tag, war_id):
    """Ensure the structure for a given war ID exists in prep_notifications."""
    global prep_notifications
    if clan_tag not in prep_notifications:
        prep_notifications[clan_tag] = {"channel": None, "notifiers": [], "wars": {}}
    if "wars" not in prep_notifications[clan_tag]:
        prep_notifications[clan_tag]["wars"] = {}
    if war_id not in prep_notifications[clan_tag]["wars"]:
        prep_notifications[clan_tag]["wars"][war_id] = {"1_hour_reminder_sent": False}


async def process_normal_war_prep(clan_tag, war_data, prep_data):
    """Process preparation notifications for normal wars."""
    war_end_time_str = war_data.get("endTime")
    war_id = f"{war_end_time_str}"

    ensure_war_data_exists(clan_tag, war_id)

    time_until_start = calculate_time_until_war_end(war_end_time_str, "preparation")
    logging.info(f"Normal war time until start for clan {clan_tag}: {time_until_start}")

    clan_name = war_data.get("clan", {}).get("name", "Ukendt Klan")
    reminder_sent = prep_data["wars"][war_id].get("1_hour_reminder_sent", False)
    logging.info(f"Normal war reminder sent: {reminder_sent}")
    if (
        timedelta(hours=1, minutes=5) >= time_until_start > timedelta(minutes=25)
        and not reminder_sent
    ):
        prep_channel_id = prep_data.get("channel", prep_channel)
        notifiers = prep_data.get("notifiers", [])

        if prep_channel_id and notifiers:
            channel = bot.get_channel(prep_channel_id)
            notifier_mentions = ", ".join([f"<@{user_id}>" for user_id in notifiers])

            if channel:
                try:
                    await channel.send(
                        f"⚠️ Forberedelses-påmindelse for klan {clan_name} {clan_tag}:\n"
                        f"{notifier_mentions}, der er mindre end 1 time tilbage før krigen starter!!"
                    )
                    logging.info(f"Sent normal preparation reminder for war {war_id}.")

                    prep_notifications[clan_tag]["wars"][war_id][
                        "1_hour_reminder_sent"
                    ] = True

                    save_data(PREP_NOTIFICATION_FILE, prep_notifications)
                except Exception as e:
                    logging.error(
                        f"Failed to send normal prep reminder for war {war_id}: {e}"
                    )


async def process_cwl_prep(clan_tag, league_data, prep_data):
    if league_data.get("state") != "preparation":
        logging.info(f"Not in CWL preparation phase for clan {clan_tag}")
        return

    clan_name = next(
        (
            clan.get("name")
            for clan in league_data.get("clans", [])
            if clan.get("tag") == clan_tag
        ),
        None,
    )
    if not clan_name:
        logging.warning(f"Could not find clan name for {clan_tag} in league data")
        return

    war_id = f"cwl_prep_{league_data.get('season', 'unknown')}"
    ensure_war_data_exists(clan_tag, war_id)

    war_tag = next(
        (
            tag
            for round_data in league_data.get("rounds", [])
            for tag in round_data.get("warTags")
            if tag != "#0"
        ),
        None,
    )
    if not war_tag:
        logging.error(f"No valid war tags found for clan {clan_tag}")
        return

    war_data = await make_coc_request_async(
        f"clanwarleagues/wars/{war_tag.replace('#', '%23')}"
    )
    if not war_data:
        logging.error(f"Could not fetch war data for warTag {war_tag}")
        return

    try:
        prep_end_time = datetime.strptime(
            war_data["startTime"], "%Y%m%dT%H%M%S.%fZ"
        ).replace(tzinfo=timezone.utc)
        logging.info(f"Prep end time determined from war data: {prep_end_time}")
    except KeyError as e:
        logging.error(f"Could not find startTime in war data for warTag {war_tag}: {e}")
        return

    current_time = datetime.now(timezone.utc)
    time_until_prep_end = prep_end_time - current_time

    logging.info(f"Current time (UTC): {current_time}")
    logging.info(f"Time until prep ends: {time_until_prep_end}")

    reminder_sent = prep_notifications[clan_tag]["wars"][war_id].get(
        "1_hour_reminder_sent", False
    )

    should_send = timedelta(minutes=60) >= time_until_prep_end > timedelta(minutes=55)
    logging.info(f"CWL Reminder already sent: {reminder_sent}")
    logging.info(f"Should send reminder: {should_send}")

    if should_send and not reminder_sent:
        prep_channel_id = prep_notifications[clan_tag].get("channel", prep_channel)
        notifiers = prep_notifications[clan_tag].get("notifiers", [])

        if prep_channel_id and notifiers:
            channel = bot.get_channel(prep_channel_id)
            if channel:
                notifier_mentions = ", ".join(
                    [f"<@{user_id}>" for user_id in notifiers]
                )
                try:
                    message = (
                        f"🎯 **CWL Forberedelses-påmindelse for {clan_name}** ({clan_tag})\n\n"
                        f"> 🔔 **Opmærksomhed:** {notifier_mentions}\n"
                        f"> ⏳ **Tid tilbage:** Mindre end 1 time tilbage af forberedelsesfasen!\n\n"
                        f"⚔️ **Husk at sætte CWL lineup og tjek CC! 🏆**\n"
                        f"Sørg for, at alt er klar til kamp - flæk flæk! 💪🚀"
                    )

                    await channel.send(message)
                    logging.info(
                        f"Successfully sent CWL prep reminder for clan {clan_tag}"
                    )

                    prep_notifications[clan_tag]["wars"][war_id][
                        "1_hour_reminder_sent"
                    ] = True
                    save_data(PREP_NOTIFICATION_FILE, prep_notifications)
                except Exception as e:
                    logging.error(f"Failed to send CWL prep reminder: {str(e)}")
            else:
                logging.error(f"Could not find channel with ID {prep_channel_id}")
        else:
            logging.warning(
                f"No prep channel ID ({prep_channel_id}) or notifiers ({notifiers}) configured"
            )


# endregion


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    setup()  # Remove await
    await bot.sync_all_application_commands()
    print("Slash commands synced globally!")
    reminder_check.start()


bot.run(DISCORD_BOT_TOKEN)
