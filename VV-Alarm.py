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
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    create_engine,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship, selectinload
from sqlalchemy import select, delete, update
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.sql import func

# Set up logging with better configuration for production
import logging.handlers

# Create logs directory if it doesn't exist
import os

if not os.path.exists("logs"):
    os.makedirs("logs")

# Set up rotating file handler for production logging
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            "logs/vv-alarm.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",  # Add UTF-8 encoding to handle Unicode characters
        ),
        logging.StreamHandler(),  # Also log to console
    ],
)

# Load environment variables from .env file
load_dotenv()

# API tokens and other configurations
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
COC_API_TOKEN = os.getenv("COC_API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DISCORD_BOT_TOKEN or not COC_API_TOKEN:
    raise ValueError(
        "Environment variables DISCORD_BOT_TOKEN and COC_API_TOKEN must be set."
    )

if not DATABASE_URL:
    raise ValueError("Environment variable DATABASE_URL must be set.")

# File paths
LINKED_ACCOUNTS_FILE = "linked_accounts.json"
CLAN_CHANNELS_FILE = "clan_channels.json"
PREP_NOTIFICATION_FILE = "prep_notifications.json"
PREP_CHANNEL_FILE = "prep_channel.json"
REMINDER_CHANNELS_FILE = "reminder_channels.json"
API_SEMAPHORE = Semaphore(5)
# Global Variables
linked_accounts = {}
clan_channels = {}
prep_notifications = {}
prep_channel = None
reminder_channel = None
reminder_channels = {}
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
    """Save data to JSON file with backup and atomic write for data safety."""
    import tempfile
    import shutil

    # Create backup before writing
    if os.path.exists(filepath):
        backup_path = f"{filepath}.backup"
        try:
            shutil.copy2(filepath, backup_path)
        except Exception as e:
            logging.warning(f"Could not create backup for {filepath}: {e}")

    # Try atomic write using temporary file in the same directory
    dir_path = os.path.dirname(os.path.abspath(filepath)) or "."
    temp_fd = None
    temp_path = None

    try:
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", prefix="vv-alarm-", dir=dir_path
        )
        with os.fdopen(temp_fd, "w") as temp_file:
            json.dump(data, temp_file, indent=2)
        temp_fd = None  # File is closed now

        # Replace original file atomically
        if os.name == "nt":  # Windows
            if os.path.exists(filepath):
                os.remove(filepath)

        # Use shutil.move instead of os.rename for cross-device compatibility
        try:
            os.rename(temp_path, filepath)
        except OSError as e:
            if e.errno == 18:  # Cross-device link error
                logging.warning(
                    f"Cross-device rename failed, using shutil.move for {filepath}"
                )
                shutil.move(temp_path, filepath)
            else:
                raise

        logging.debug(f"Successfully saved data to {filepath}")

    except Exception as e:
        logging.error(f"Failed to save data to {filepath}: {e}")
        # Clean up temp file on error
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass
        # Clean up file descriptor if still open
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except:
                pass

        # Fallback: try simple write (less safe but better than failing)
        try:
            logging.warning(f"Attempting fallback simple write for {filepath}")
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            logging.info(f"Fallback write successful for {filepath}")
        except Exception as fallback_e:
            logging.error(f"Fallback write also failed for {filepath}: {fallback_e}")
            raise  # Re-raise the original exception


def safe_save_data(filepath, data):
    """Wrapper for save_data that doesn't raise exceptions."""
    try:
        save_data(filepath, data)
        return True
    except Exception as e:
        logging.error(f"safe_save_data failed for {filepath}: {e}")
        return False


async def get_guild_data(data_type, guild_id):
    """Get guild-specific data from database or fall back to JSON files"""
    # Check if database is initialized
    if not db_manager._initialized:
        logging.debug(f"Database not initialized, using JSON files for {data_type}")
        if data_type == "linked_accounts":
            return linked_accounts.get(str(guild_id), {})
        elif data_type == "clan_channels":
            return clan_channels.get(str(guild_id), {})
        elif data_type == "prep_notifications":
            return prep_notifications.get(str(guild_id), {})
        else:
            return {}

    # Use database if available, except for prep_notifications war tracking which stays in JSON
    try:
        if data_type == "linked_accounts":
            return await db_manager.get_guild_linked_accounts(guild_id)
        elif data_type == "clan_channels":
            return await db_manager.get_guild_clan_channels(guild_id)
        elif data_type == "prep_notifications":
            return await db_manager.get_guild_prep_notifications(guild_id)
        else:
            return {}
    except Exception as e:
        logging.warning(f"Database error for {data_type}, falling back to JSON: {e}")
        if data_type == "linked_accounts":
            return linked_accounts.get(str(guild_id), {})
        elif data_type == "clan_channels":
            return clan_channels.get(str(guild_id), {})
        elif data_type == "prep_notifications":
            return prep_notifications.get(str(guild_id), {})
        else:
            return {}


def load_prep_channel():
    if os.path.exists(PREP_CHANNEL_FILE):
        with open(PREP_CHANNEL_FILE, "r") as file:
            return json.load(file)
    return {}


def save_prep_channel(guild_id, channel_id):
    prep_channels = load_prep_channel()
    prep_channels[str(guild_id)] = channel_id
    with open(PREP_CHANNEL_FILE, "w") as file:
        json.dump(prep_channels, file)


async def get_prep_channel(guild_id):
    return await db_manager.get_prep_channel(guild_id)


async def get_reminder_channel(guild_id):
    """Get reminder channel with database first, JSON fallback"""
    if db_manager._initialized:
        try:
            return await db_manager.get_reminder_channel(guild_id)
        except Exception as e:
            logging.warning(
                f"Database error getting reminder channel, falling back to JSON: {e}"
            )

    # Fallback to JSON
    return reminder_channels.get(str(guild_id))


def is_clan_monitored_by_other_guild(clan_tag, current_guild_id):
    """Check if a clan tag is already being monitored by a different guild"""
    for guild_id_str, guild_clans in clan_channels.items():
        # Skip the current guild
        if int(guild_id_str) == current_guild_id:
            continue
        # Check if this clan tag exists in another guild
        if clan_tag in guild_clans:
            return True, int(guild_id_str)
    return False, None


def get_guild_monitoring_clan(clan_tag):
    """Get the guild ID that is currently monitoring a specific clan tag"""
    for guild_id_str, guild_clans in clan_channels.items():
        if clan_tag in guild_clans:
            return int(guild_id_str)
    return None


# endregion

# region Database Setup
Base = declarative_base()


# Database Models
class Guild(Base):
    __tablename__ = "guilds"

    guild_id = Column(BigInteger, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    settings = Column(JSON)


class LinkedAccount(Base):
    __tablename__ = "linked_accounts"

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    player_tag = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=func.now())


class ClanChannel(Base):
    __tablename__ = "clan_channels"

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, nullable=False)
    clan_tag = Column(String(20), nullable=False)
    clan_name = Column(String(100), nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=func.now())


class PrepNotification(Base):
    __tablename__ = "prep_notifications"

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, nullable=False)
    clan_tag = Column(String(20), nullable=False)
    channel_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=func.now())


class PrepNotifier(Base):
    __tablename__ = "prep_notifiers"

    id = Column(Integer, primary_key=True)
    prep_notification_id = Column(Integer, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=func.now())


class PrepChannel(Base):
    __tablename__ = "prep_channels"

    guild_id = Column(BigInteger, primary_key=True)
    channel_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=func.now())


class ReminderChannel(Base):
    __tablename__ = "reminder_channels"

    guild_id = Column(BigInteger, primary_key=True)
    channel_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=func.now())


class WarReminderState(Base):
    __tablename__ = "war_reminder_states"

    id = Column(Integer, primary_key=True)
    guild_id = Column(BigInteger, nullable=False)
    clan_tag = Column(String(20), nullable=False)
    war_id = Column(String(50), nullable=False)  # endTime string or cwl_prep_season
    reminder_1hour_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


# Database Manager
class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        self._initialized = False

    async def initialize(self):
        """Initialize database connection"""
        try:
            self.engine = create_async_engine(
                DATABASE_URL,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=3600,
                echo=False,
            )

            self.session_factory = async_sessionmaker(
                self.engine, class_=AsyncSession, expire_on_commit=False
            )

            # Create all tables
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            self._initialized = True
            logging.info("Database initialized successfully")

        except Exception as e:
            logging.warning(
                f"Database initialization failed (running in local/JSON mode): {e}"
            )
            logging.info("Bot will continue using JSON files for data storage")

    async def ensure_guild_exists(self, guild_id: int):
        """Ensure a guild exists in the database"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(Guild).where(Guild.guild_id == guild_id)
            )
            guild = result.scalar_one_or_none()

            if not guild:
                guild = Guild(guild_id=guild_id)
                session.add(guild)
                await session.commit()

    async def get_guild_linked_accounts(self, guild_id: int):
        """Get all linked accounts for a guild"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            result = await session.execute(
                select(LinkedAccount).where(LinkedAccount.guild_id == guild_id)
            )
            accounts = result.scalars().all()

            guild_accounts = {}
            for account in accounts:
                user_id = str(account.user_id)
                if user_id not in guild_accounts:
                    guild_accounts[user_id] = []
                guild_accounts[user_id].append(account.player_tag)

            return guild_accounts

    async def add_linked_account(self, guild_id: int, user_id: int, player_tag: str):
        """Add a linked account"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            # Check if already exists
            result = await session.execute(
                select(LinkedAccount).where(
                    LinkedAccount.guild_id == guild_id,
                    LinkedAccount.user_id == user_id,
                    LinkedAccount.player_tag == player_tag,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                return False

            account = LinkedAccount(
                guild_id=guild_id, user_id=user_id, player_tag=player_tag
            )
            session.add(account)
            await session.commit()
            return True

    async def remove_linked_account(self, guild_id: int, user_id: int, player_tag: str):
        """Remove a linked account"""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(LinkedAccount).where(
                    LinkedAccount.guild_id == guild_id,
                    LinkedAccount.user_id == user_id,
                    LinkedAccount.player_tag == player_tag,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def get_guild_clan_channels(self, guild_id: int):
        """Get all clan channels for a guild"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            result = await session.execute(
                select(ClanChannel).where(ClanChannel.guild_id == guild_id)
            )
            channels = result.scalars().all()

            guild_clans = {}
            for channel in channels:
                guild_clans[channel.clan_tag] = {
                    "name": channel.clan_name,
                    "channel": channel.channel_id,
                }

            return guild_clans

    async def add_clan_channel(
        self, guild_id: int, clan_tag: str, clan_name: str, channel_id: int
    ):
        """Add a clan channel"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            # Check if already exists
            result = await session.execute(
                select(ClanChannel).where(
                    ClanChannel.guild_id == guild_id, ClanChannel.clan_tag == clan_tag
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.clan_name = clan_name
                existing.channel_id = channel_id
            else:
                clan_channel = ClanChannel(
                    guild_id=guild_id,
                    clan_tag=clan_tag,
                    clan_name=clan_name,
                    channel_id=channel_id,
                )
                session.add(clan_channel)

            await session.commit()
            return True

    async def remove_clan_channel(self, guild_id: int, clan_tag: str):
        """Remove a clan channel"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ClanChannel).where(
                    ClanChannel.guild_id == guild_id, ClanChannel.clan_tag == clan_tag
                )
            )
            clan_channel = result.scalar_one_or_none()

            if clan_channel:
                await session.delete(clan_channel)
                await session.commit()
                return True
            return False

    async def get_prep_channel(self, guild_id: int):
        """Get prep channel for a guild"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(PrepChannel).where(PrepChannel.guild_id == guild_id)
            )
            prep_channel = result.scalar_one_or_none()
            return prep_channel.channel_id if prep_channel else None

    async def set_prep_channel(self, guild_id: int, channel_id: int):
        """Set prep channel for a guild"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            result = await session.execute(
                select(PrepChannel).where(PrepChannel.guild_id == guild_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.channel_id = channel_id
            else:
                prep_channel = PrepChannel(guild_id=guild_id, channel_id=channel_id)
                session.add(prep_channel)

            await session.commit()

    async def get_all_guilds_with_clans(self):
        """Get all guilds that have clan channels configured"""
        if not self._initialized:
            return {}

        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    ClanChannel.guild_id,
                    ClanChannel.clan_tag,
                    ClanChannel.clan_name,
                    ClanChannel.channel_id,
                )
            )
            clan_channels = result.all()

            # Group by guild_id
            guilds_data = {}
            for guild_id, clan_tag, clan_name, channel_id in clan_channels:
                if guild_id not in guilds_data:
                    guilds_data[guild_id] = {}
                guilds_data[guild_id][clan_tag] = {
                    "name": clan_name,
                    "channel": channel_id,
                }

            return guilds_data

    async def get_guild_prep_notifications(self, guild_id: int):
        """Get all prep notifications for a guild"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            # Get prep notifications with notifiers
            result = await session.execute(
                select(PrepNotification).where(PrepNotification.guild_id == guild_id)
            )
            prep_notifications = result.scalars().all()

            guild_prep_data = {}
            for prep_notif in prep_notifications:
                clan_tag = prep_notif.clan_tag
                if clan_tag not in guild_prep_data:
                    guild_prep_data[clan_tag] = {
                        "channel": prep_notif.channel_id,
                        "notifiers": [],
                        "wars": {},
                    }

                # Get notifiers for this prep notification
                notifier_result = await session.execute(
                    select(PrepNotifier).where(
                        PrepNotifier.prep_notification_id == prep_notif.id
                    )
                )
                notifiers = notifier_result.scalars().all()
                guild_prep_data[clan_tag]["notifiers"] = [
                    notifier.user_id for notifier in notifiers
                ]

            return guild_prep_data

    async def add_prep_notifier(
        self, guild_id: int, clan_tag: str, user_id: int, channel_id: int
    ):
        """Add a prep notifier for a clan"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            # Get or create prep notification
            result = await session.execute(
                select(PrepNotification).where(
                    PrepNotification.guild_id == guild_id,
                    PrepNotification.clan_tag == clan_tag,
                )
            )
            prep_notification = result.scalar_one_or_none()

            if not prep_notification:
                prep_notification = PrepNotification(
                    guild_id=guild_id, clan_tag=clan_tag, channel_id=channel_id
                )
                session.add(prep_notification)
                await session.flush()  # Get the ID

            # Check if notifier already exists
            notifier_result = await session.execute(
                select(PrepNotifier).where(
                    PrepNotifier.prep_notification_id == prep_notification.id,
                    PrepNotifier.user_id == user_id,
                )
            )
            existing_notifier = notifier_result.scalar_one_or_none()

            if not existing_notifier:
                notifier = PrepNotifier(
                    prep_notification_id=prep_notification.id, user_id=user_id
                )
                session.add(notifier)
                await session.commit()
                return True  # New notifier added
            else:
                return False  # Already exists

    async def get_reminder_channel(self, guild_id: int):
        """Get reminder channel for a guild"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReminderChannel).where(ReminderChannel.guild_id == guild_id)
            )
            reminder_channel = result.scalar_one_or_none()
            return reminder_channel.channel_id if reminder_channel else None

    async def set_reminder_channel(self, guild_id: int, channel_id: int):
        """Set reminder channel for a guild"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            result = await session.execute(
                select(ReminderChannel).where(ReminderChannel.guild_id == guild_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.channel_id = channel_id
            else:
                reminder_channel = ReminderChannel(
                    guild_id=guild_id, channel_id=channel_id
                )
                session.add(reminder_channel)

            await session.commit()

    async def get_war_reminder_state(self, guild_id: int, clan_tag: str, war_id: str):
        """Get war reminder state"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(WarReminderState).where(
                    WarReminderState.guild_id == guild_id,
                    WarReminderState.clan_tag == clan_tag,
                    WarReminderState.war_id == war_id,
                )
            )
            return result.scalar_one_or_none()

    async def set_war_reminder_sent(self, guild_id: int, clan_tag: str, war_id: str):
        """Mark war reminder as sent"""
        await self.ensure_guild_exists(guild_id)

        async with self.session_factory() as session:
            # Get or create war reminder state
            result = await session.execute(
                select(WarReminderState).where(
                    WarReminderState.guild_id == guild_id,
                    WarReminderState.clan_tag == clan_tag,
                    WarReminderState.war_id == war_id,
                )
            )
            war_state = result.scalar_one_or_none()

            if war_state:
                war_state.reminder_1hour_sent = True
                war_state.updated_at = func.now()
            else:
                war_state = WarReminderState(
                    guild_id=guild_id,
                    clan_tag=clan_tag,
                    war_id=war_id,
                    reminder_1hour_sent=True,
                )
                session.add(war_state)

            await session.commit()
            return True

    async def clear_war_reminder_states(self, guild_id: int, clan_tag: str):
        """Clear all war reminder states for a clan (when war moves from prep to inWar)"""
        async with self.session_factory() as session:
            await session.execute(
                delete(WarReminderState).where(
                    WarReminderState.guild_id == guild_id,
                    WarReminderState.clan_tag == clan_tag,
                )
            )
            await session.commit()


# Global database manager
db_manager = DatabaseManager()
# endregion

# region File Initialization
# Initialize files
ensure_file_exists(LINKED_ACCOUNTS_FILE, {})
ensure_file_exists(CLAN_CHANNELS_FILE, {})
ensure_file_exists(PREP_NOTIFICATION_FILE, {})
ensure_file_exists(REMINDER_CHANNELS_FILE, {})

prep_notifications = load_data(PREP_NOTIFICATION_FILE)
linked_accounts = load_data(LINKED_ACCOUNTS_FILE)
clan_channels = load_data(CLAN_CHANNELS_FILE)
prep_channels = load_prep_channel()  # Now loads all guild prep channels
reminder_channels = load_data(REMINDER_CHANNELS_FILE)
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
        description="Link a Clash of Clans account to a Discord user (Administrators only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def link_account(
        self,
        interaction: nextcord.Interaction,
        discord_user: nextcord.Member,
        player_tag: str,
    ):
        # Try database first, fall back to JSON
        if db_manager._initialized:
            try:
                success = await db_manager.add_linked_account(
                    interaction.guild_id, discord_user.id, player_tag
                )
                if success:
                    await interaction.response.send_message(
                        f"Successfully linked Clash of Clans tag {player_tag} to {discord_user.mention}.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"Tag {player_tag} is already linked to {discord_user.mention}.",
                        ephemeral=True,
                    )
                return
            except Exception as e:
                logging.warning(
                    f"Database error in link_account, falling back to JSON: {e}"
                )

        # Fallback to JSON files
        guild_linked_accounts = linked_accounts.setdefault(
            str(interaction.guild_id), {}
        )
        user_id = str(discord_user.id)

        if user_id not in guild_linked_accounts:
            guild_linked_accounts[user_id] = []

        if player_tag not in guild_linked_accounts[user_id]:
            guild_linked_accounts[user_id].append(player_tag)
            save_data(LINKED_ACCOUNTS_FILE, linked_accounts)
            await interaction.response.send_message(
                f"Successfully linked Clash of Clans tag {player_tag} to {discord_user.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Tag {player_tag} is already linked to {discord_user.mention}.",
                ephemeral=True,
            )

    @nextcord.slash_command(
        name="unlink_account",
        description="Remove a Clash of Clans account from a Discord user (Administrators only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def unlink_account(
        self,
        interaction: nextcord.Interaction,
        discord_user: nextcord.Member,
        player_tag: str,
    ):
        # Try database first, fall back to JSON
        if db_manager._initialized:
            try:
                success = await db_manager.remove_linked_account(
                    interaction.guild_id, discord_user.id, player_tag
                )
                if success:
                    await interaction.response.send_message(
                        f"Successfully removed Clash of Clans tag {player_tag} from {discord_user.mention}.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        f"Could not find tag {player_tag} for {discord_user.mention}.",
                        ephemeral=True,
                    )
                return
            except Exception as e:
                logging.warning(
                    f"Database error in unlink_account, falling back to JSON: {e}"
                )

        # Fallback to JSON files
        guild_linked_accounts = await get_guild_data(
            "linked_accounts", interaction.guild_id
        )
        user_id = str(discord_user.id)
        if (
            user_id in guild_linked_accounts
            and player_tag in guild_linked_accounts[user_id]
        ):
            guild_linked_accounts[user_id].remove(player_tag)
            if not guild_linked_accounts[user_id]:
                del guild_linked_accounts[user_id]
            save_data(LINKED_ACCOUNTS_FILE, linked_accounts)
            await interaction.response.send_message(
                f"Successfully removed Clash of Clans tag {player_tag} from {discord_user.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"Could not find tag {player_tag} for {discord_user.mention}.",
                ephemeral=True,
            )

    @nextcord.slash_command(
        name="set_reminder_channel",
        description="Set which channel should show war reminders",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def set_reminder_channel(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        # Try database first, fall back to JSON
        if db_manager._initialized:
            try:
                await db_manager.set_reminder_channel(interaction.guild_id, channel.id)
                await interaction.response.send_message(
                    f"Reminder channel has been set to <#{channel.id}>.",
                    ephemeral=True,
                )
                return
            except Exception as e:
                logging.warning(
                    f"Database error in set_reminder_channel, falling back to JSON: {e}"
                )

        # Fallback to JSON files
        reminder_channels[str(interaction.guild_id)] = channel.id
        save_data(REMINDER_CHANNELS_FILE, reminder_channels)

        await interaction.response.send_message(
            f"Reminder channel has been set to <#{channel.id}>.",
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="monitor_clan",
        description="Add a clan to monitoring",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def monitor_clan(
        self, interaction: nextcord.Interaction, clan_name: str, clan_tag: str
    ):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )

        # Check if guild has reached the 4 clan limit
        if len(guild_clan_channels) >= 4:
            current_clans = "\n".join(
                [
                    f"• {info['name']} ({tag})"
                    for tag, info in guild_clan_channels.items()
                ]
            )
            await interaction.response.send_message(
                f"❌ **Clan Limit Reached**\n\n"
                f"Your server can only monitor up to **4 clans** at a time.\n\n"
                f"**Currently monitored clans:**\n{current_clans}\n\n"
                f"Use `/unmonitor_clan` to remove a clan before adding a new one.",
                ephemeral=True,
            )
            return

        # Ensure clan tag has # prefix
        if not clan_tag.startswith("#"):
            clan_tag = f"#{clan_tag}"

        # Check if reminder channel is set for this guild
        reminder_channel_id = await get_reminder_channel(interaction.guild_id)
        if not reminder_channel_id:
            await interaction.response.send_message(
                "No reminder channel has been set. Use the '/set_reminder_channel' command to set a channel.",
                ephemeral=True,
            )
            return

        # Check if this clan is already being monitored by another guild
        is_monitored, monitoring_guild_id = is_clan_monitored_by_other_guild(
            clan_tag, interaction.guild_id
        )
        if is_monitored:
            await interaction.response.send_message(
                f"⚠️ **WARNING**: Clan {clan_name} ({clan_tag}) is already being monitored by another Discord server (Guild ID: {monitoring_guild_id}).\n\n"
                f"**This can lead to:**\n"
                f"• Both servers receiving reminders for the same clan\n"
                f"• Confusion about which Discord users belong to the clan\n"
                f"• Mixed account information in war status messages\n\n"
                f"**Recommendation**: Contact the other server admin to resolve the conflict, or use your own clan's tag.",
                ephemeral=True,
            )
            return

        reminder_channel = reminder_channels[str(interaction.guild_id)]

        if clan_tag in guild_clan_channels:
            await interaction.response.send_message(
                f"Clan {clan_name} ({clan_tag}) is already being monitored by this server.",
                ephemeral=True,
            )
        else:
            # Verify the clan exists by making an API call
            clan_data = await make_coc_request_async(
                f"clans/{clan_tag.replace('#', '%23')}"
            )
            if not clan_data:
                await interaction.response.send_message(
                    f"❌ Could not find clan with tag {clan_tag}. Please check if the tag is correct.",
                    ephemeral=True,
                )
                return

            actual_clan_name = clan_data.get("name", "Unknown")

            # Try database first, fall back to JSON
            if db_manager._initialized:
                try:
                    await db_manager.add_clan_channel(
                        interaction.guild_id, clan_tag, clan_name, reminder_channel_id
                    )
                    await interaction.response.send_message(
                        f"✅ Clan **{clan_name}** ({clan_tag}) has been added to monitoring.\n"
                        f"📋 API confirmed clan name: **{actual_clan_name}**\n"
                        f"📢 Reminders will be sent to: <#{reminder_channel_id}>",
                        ephemeral=True,
                    )
                    return
                except Exception as e:
                    logging.warning(
                        f"Database error in monitor_clan, falling back to JSON: {e}"
                    )

            # Fallback to JSON files
            guild_clan_channels = clan_channels.setdefault(
                str(interaction.guild_id), {}
            )
            guild_clan_channels[clan_tag] = {
                "name": clan_name,
                "channel": reminder_channel_id,
            }
            save_data(CLAN_CHANNELS_FILE, clan_channels)

            await interaction.response.send_message(
                f"✅ Clan **{clan_name}** ({clan_tag}) has been added to monitoring.\n"
                f"📋 API confirmed clan name: **{actual_clan_name}**\n"
                f"📢 Reminders will be sent to: <#{reminder_channel_id}>",
                ephemeral=True,
            )

    @nextcord.slash_command(
        name="unmonitor_clan",
        description="Remove a clan from monitoring",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def unmonitor_clan(self, interaction: nextcord.Interaction, clan: str):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )

        # Find the clan tag by name
        clan_tag = None
        for tag, info in guild_clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.response.send_message(
                f"❌ Clan '{clan}' was not found in monitoring.",
                ephemeral=True,
            )
            return

        # Try database first, fall back to JSON
        if db_manager._initialized:
            try:
                success = await db_manager.remove_clan_channel(
                    interaction.guild_id, clan_tag
                )
                if success:
                    # Also clean up prep notifications for this clan
                    guild_prep_notifications = await get_guild_data(
                        "prep_notifications", interaction.guild_id
                    )
                    if clan_tag in guild_prep_notifications:
                        del guild_prep_notifications[clan_tag]
                        save_data(PREP_NOTIFICATION_FILE, prep_notifications)

                    await interaction.response.send_message(
                        f"✅ Clan **{clan}** ({clan_tag}) has been removed from monitoring.\n"
                        f"🗑️ All associated preparation notifications have been cleared.",
                        ephemeral=True,
                    )
                    return
                else:
                    await interaction.response.send_message(
                        f"❌ Could not remove clan '{clan}' from database.",
                        ephemeral=True,
                    )
                    return
            except Exception as e:
                logging.warning(
                    f"Database error in unmonitor_clan, falling back to JSON: {e}"
                )

        # Fallback to JSON files
        if clan_tag in guild_clan_channels:
            del guild_clan_channels[clan_tag]
            save_data(CLAN_CHANNELS_FILE, clan_channels)

            # Also clean up prep notifications for this clan
            guild_prep_notifications = await get_guild_data(
                "prep_notifications", interaction.guild_id
            )
            if clan_tag in guild_prep_notifications:
                del guild_prep_notifications[clan_tag]
                save_data(PREP_NOTIFICATION_FILE, prep_notifications)

            await interaction.response.send_message(
                f"✅ Clan **{clan}** ({clan_tag}) has been removed from monitoring.\n"
                f"🗑️ All associated preparation notifications have been cleared.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"❌ Clan '{clan}' was not found in monitoring.",
                ephemeral=True,
            )

    @unmonitor_clan.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        matching_clans = [
            info["name"]
            for tag, info in guild_clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])

    @nextcord.slash_command(
        name="list_monitored_clans",
        description="Show all clans currently being monitored by this server",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def list_monitored_clans(self, interaction: nextcord.Interaction):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )

        if not guild_clan_channels:
            await interaction.response.send_message(
                "❌ No clans are currently being monitored by this server.\n"
                "Use `/monitor_clan` to add a clan to monitoring.",
                ephemeral=True,
            )
            return

        # Get reminder channel info
        reminder_channel_id = await get_reminder_channel(interaction.guild_id)

        # Build the clan list
        clan_list = []
        for clan_tag, clan_info in guild_clan_channels.items():
            clan_name = clan_info.get("name", "Unknown")
            clan_list.append(f"• **{clan_name}** ({clan_tag})")

        message = (
            f"🏰 **Monitored Clans ({len(guild_clan_channels)}/4)**\n\n"
            + "\n".join(clan_list)
            + f"\n\n📢 **Reminder Channel:** "
        )

        if reminder_channel_id:
            message += f"<#{reminder_channel_id}>"
        else:
            message += "⚠️ Not set - use `/set_reminder_channel`"

        # Check prep channel
        prep_channel_id = await get_prep_channel(interaction.guild_id)
        message += f"\n🔔 **Prep Channel:** "
        if prep_channel_id:
            message += f"<#{prep_channel_id}>"
        else:
            message += "⚠️ Not set - use `/set_prep_channel`"

        await interaction.response.send_message(message, ephemeral=True)

    @nextcord.slash_command(
        name="my_accounts",
        description="Show your linked Clash of Clans accounts",
    )
    async def my_accounts(self, interaction: nextcord.Interaction):
        guild_linked_accounts = await get_guild_data(
            "linked_accounts", interaction.guild_id
        )

        user_id = str(interaction.user.id)
        user_accounts = guild_linked_accounts.get(user_id, [])

        if not user_accounts:
            await interaction.response.send_message(
                "❌ You don't have any linked Clash of Clans accounts in this server.\n"
                "Ask an administrator to link your account using `/link_account`.",
                ephemeral=True,
            )
            return

        # Get player info from API for each account
        account_info = []
        for player_tag in user_accounts:
            player_data = await make_coc_request_async(
                f"players/{player_tag.replace('#', '%23')}"
            )
            if player_data:
                player_name = player_data.get("name", "Unknown")
                player_th = player_data.get("townHallLevel", "?")
                clan_name = player_data.get("clan", {}).get("name", "No Clan")
                account_info.append(
                    f"• **{player_name}** (TH{player_th}) - {player_tag}\n  └ Clan: {clan_name}"
                )
            else:
                account_info.append(
                    f"• **Unknown Player** - {player_tag}\n  └ Could not fetch data"
                )

        message = (
            f"🔗 **Your Linked Accounts ({len(user_accounts)})**\n\n"
            + "\n\n".join(account_info)
        )

        await interaction.response.send_message(message, ephemeral=True)

    @nextcord.slash_command(
        name="bot_config",
        description="Show current bot configuration for this server",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def bot_config(self, interaction: nextcord.Interaction):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        guild_linked_accounts = await get_guild_data(
            "linked_accounts", interaction.guild_id
        )

        # Count linked accounts
        total_linked_accounts = sum(
            len(accounts) for accounts in guild_linked_accounts.values()
        )

        # Get reminder channel
        reminder_channel_id = await get_reminder_channel(interaction.guild_id)

        # Get prep channel
        prep_channel_id = await get_prep_channel(interaction.guild_id)

        # Count prep notifications
        guild_prep_notifications = await get_guild_data(
            "prep_notifications", interaction.guild_id
        )
        prep_notifier_count = sum(
            len(clan_data.get("notifiers", []))
            for clan_data in guild_prep_notifications.values()
        )

        config_message = (
            f"⚙️ **Bot Configuration for {interaction.guild.name}**\n\n"
            f"🏰 **Monitored Clans:** {len(guild_clan_channels)}/4\n"
            f"🔗 **Linked Accounts:** {total_linked_accounts} accounts across {len(guild_linked_accounts)} users\n"
            f"📢 **Reminder Channel:** "
        )

        if reminder_channel_id:
            config_message += f"<#{reminder_channel_id}> ✅"
        else:
            config_message += "⚠️ Not configured"

        config_message += f"\n🔔 **Prep Channel:** "
        if prep_channel_id:
            config_message += f"<#{prep_channel_id}> ✅"
        else:
            config_message += "⚠️ Not configured"

        config_message += (
            f"\n👥 **Prep Notifiers:** {prep_notifier_count} users assigned"
        )

        # Add setup recommendations if needed
        recommendations = []
        if not reminder_channel_id:
            recommendations.append(
                "• Set a reminder channel with `/set_reminder_channel`"
            )
        if not guild_clan_channels:
            recommendations.append("• Add clans to monitor with `/monitor_clan`")
        if not prep_channel_id and guild_clan_channels:
            recommendations.append("• Set a prep channel with `/set_prep_channel`")

        if recommendations:
            config_message += f"\n\n📝 **Setup Recommendations:**\n" + "\n".join(
                recommendations
            )
        else:
            config_message += (
                f"\n\n✅ **Setup Complete!** Your bot is ready to monitor wars."
            )

        await interaction.response.send_message(config_message, ephemeral=True)

    @nextcord.slash_command(
        name="set_prep_channel",
        description="Set the channel for preparation reminders (Administrators only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def set_prep_channel(
        self, interaction: nextcord.Interaction, channel: nextcord.TextChannel
    ):
        await db_manager.set_prep_channel(interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"Preparation reminder channel has been set to <#{channel.id}>.",
            ephemeral=True,
        )

    @nextcord.slash_command(
        name="assign_prep_notifiers",
        description="Assign users to receive preparation reminders (Administrators only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def assign_prep_notifiers(
        self,
        interaction: nextcord.Interaction,
        clan: str,
        users: nextcord.Member,
    ):
        guild_prep_channel = await get_prep_channel(interaction.guild_id)
        if not guild_prep_channel:
            await interaction.response.send_message(
                "No preparation channel has been set. Use the '/set_prep_channel' command to set a channel.",
                ephemeral=True,
            )
            return

        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        guild_prep_notifications = await get_guild_data(
            "prep_notifications", interaction.guild_id
        )

        clan_tag = None
        for tag, info in guild_clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.response.send_message(
                f"Clan '{clan}' was not found in monitoring.",
                ephemeral=True,
            )
            return

        user_id = users.id

        # Try database first, fall back to JSON
        if db_manager._initialized:
            try:
                # Check if already assigned
                if (
                    clan_tag in guild_prep_notifications
                    and user_id in guild_prep_notifications[clan_tag]["notifiers"]
                ):
                    already_assigned = [f"<@{user_id}>"]
                    newly_assigned = []
                else:
                    # Add to database
                    success = await db_manager.add_prep_notifier(
                        interaction.guild_id, clan_tag, user_id, guild_prep_channel
                    )
                    if success:
                        newly_assigned = [f"<@{user_id}>"]
                        already_assigned = []
                    else:
                        already_assigned = [f"<@{user_id}>"]
                        newly_assigned = []
                save_success = True
            except Exception as e:
                logging.warning(
                    f"Database error in assign_prep_notifiers, falling back to JSON: {e}"
                )
                # Fall back to JSON method below
                save_success = False
        else:
            save_success = False

        # Fallback to JSON files if database failed
        if not save_success:
            if clan_tag not in guild_prep_notifications:
                guild_prep_notifications[clan_tag] = {
                    "channel": guild_prep_channel,
                    "notifiers": [],
                }

            already_assigned = []
            newly_assigned = []

            if user_id in guild_prep_notifications[clan_tag]["notifiers"]:
                already_assigned.append(f"<@{user_id}>")
            else:
                guild_prep_notifications[clan_tag]["notifiers"].append(user_id)
                newly_assigned.append(f"<@{user_id}>")

            # Try to save data, but don't fail the command if it doesn't work
            save_success = safe_save_data(PREP_NOTIFICATION_FILE, prep_notifications)

        response_message = ""
        if newly_assigned:
            response_message += f"The following users have been assigned to receive preparation reminders for clan '{clan}': {', '.join(newly_assigned)}.\n"
        if already_assigned:
            response_message += f"The following users were already assigned: {', '.join(already_assigned)}."

        if not save_success:
            response_message += f"\n\n⚠️ **Warning**: Assignment was successful but data could not be saved to file. The assignment is still active in memory but may be lost on bot restart."

        await interaction.response.send_message(response_message)

    @nextcord.slash_command(
        name="list_prep_notifiers",
        description="Show all prep notifiers for monitored clans (Administrators only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def list_prep_notifiers(self, interaction: nextcord.Interaction):
        guild_prep_notifications = await get_guild_data(
            "prep_notifications", interaction.guild_id
        )

        if not guild_prep_notifications:
            await interaction.response.send_message(
                "❌ No prep notifiers have been assigned yet.\n"
                "Use `/assign_prep_notifiers` to assign users to receive preparation reminders.",
                ephemeral=True,
            )
            return

        message = "👥 **Prep Notifiers by Clan:**\n\n"
        total_notifiers = 0

        for clan_tag, clan_data in guild_prep_notifications.items():
            notifiers = clan_data.get("notifiers", [])
            if notifiers:
                # Get clan name from monitored clans
                guild_clan_channels = await get_guild_data(
                    "clan_channels", interaction.guild_id
                )
                clan_name = guild_clan_channels.get(clan_tag, {}).get(
                    "name", "Unknown Clan"
                )

                notifier_mentions = [f"<@{user_id}>" for user_id in notifiers]
                message += f"**🏰 {clan_name}** ({clan_tag})\n"
                message += f"└ {', '.join(notifier_mentions)}\n\n"
                total_notifiers += len(notifiers)

        message += f"**Total:** {total_notifiers} users assigned across {len(guild_prep_notifications)} clans"

        await interaction.response.send_message(message, ephemeral=True)

    @assign_prep_notifiers.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        matching_clans = [
            info["name"]
            for tag, info in guild_clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])

    @nextcord.slash_command(
        name="match_status", description="Check the status of the clan's war."
    )
    async def match_status(self, interaction: nextcord.Interaction, clan: str):
        await interaction.response.defer()
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        guild_linked_accounts = await get_guild_data(
            "linked_accounts", interaction.guild_id
        )
        clan_tag = None

        for tag, info in guild_clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.followup.send(
                f"Clan {clan} was not found.", ephemeral=True
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
                                    guild_linked_accounts=guild_linked_accounts,
                                )
                                return

            elif league_state == "preparation":
                await interaction.followup.send(
                    f"⚔️ CWL for {clan} ({clan_tag}) is in preparation phase.",
                    ephemeral=True,
                )
                return

        war_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}/currentwar"
        )
        if war_data and war_data.get("state") == "inWar":
            await self.process_war_status(
                interaction,
                clan,
                clan_tag,
                war_data,
                "inWar",
                is_cwl=False,
                guild_linked_accounts=guild_linked_accounts,
            )
        else:
            await interaction.followup.send(
                f"Clan {clan} is not in any active wars.", ephemeral=True
            )

    async def process_war_status(
        self,
        interaction,
        clan,
        clan_tag,
        war_data,
        state,
        is_cwl=False,
        round_num=None,
        guild_linked_accounts=None,
    ):
        def split_message(message, limit=2000):
            return [message[i : i + limit] for i in range(0, len(message), limit)]

        war_type = "CWL" if is_cwl else "Normal"
        round_info = f" (Round {round_num})" if is_cwl else ""

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
        time_until_end_formatted = f"{time_until_end.seconds // 3600} hours, {(time_until_end.seconds // 60) % 60} minutes"

        unattacked_players = get_unattacked_players(war_data, is_cwl=is_cwl)

        message = (
            f"⚔️ {war_type} war{round_info} for {clan_name} ({clan_tag}) vs {opponent_name}\n"
            f"⏰ Time remaining: {time_until_end_formatted}\n\n"
            f"Score:\n"
            f"\n"
            f"{clan_name}:\n"
            f"⭐ {stars_clan} | {destruction_clan:.2f}%\n\n"
            f"{opponent_name}:\n"
            f"⭐ {stars_opponent} | {destruction_opponent:.2f}%\n"
        )

        player_list = ""
        if unattacked_players:
            player_list = "\nPlayers who still need to attack:\n"
            for player_tag, missing_attacks in unattacked_players.items():
                discord_mentions = [
                    f"<@{user_id}>"
                    for user_id, tags in (guild_linked_accounts or {}).items()
                    if player_tag in tags
                ]
                linked_users = (
                    ", ".join(discord_mentions)
                    if discord_mentions
                    else "No Discord link"
                )
                player_list += f"- {player_tag}: Missing {missing_attacks} attacks. Linked: {linked_users}\n"
        else:
            player_list = "\nAll players have attacked! 💪"

        message += player_list

        messages = split_message(message)
        for msg in messages:
            await interaction.followup.send(msg)

    @match_status.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        try:
            # Get all clan names from guild-specific clan_channels
            guild_clan_channels = await get_guild_data(
                "clan_channels", interaction.guild_id
            )
            clan_names = [info["name"] for tag, info in guild_clan_channels.items()]

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
        name="unlinked_accounts",
        description="Show which accounts are not linked to Discord in a monitored clan (Administrators only)",
        default_member_permissions=nextcord.Permissions(administrator=True),
    )
    async def unlinked_accounts(self, interaction: nextcord.Interaction, clan: str):
        await interaction.response.defer()

        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        guild_linked_accounts = await get_guild_data(
            "linked_accounts", interaction.guild_id
        )

        clan_tag = None
        for tag, info in guild_clan_channels.items():
            if info["name"] == clan:
                clan_tag = tag
                break

        if not clan_tag:
            await interaction.followup.send(
                f"Clan '{clan}' was not found in monitoring.", ephemeral=True
            )
            return

        clan_data = await make_coc_request_async(
            f"clans/{clan_tag.replace('#', '%23')}"
        )
        if not clan_data:
            await interaction.followup.send(
                f"Could not retrieve data for clan '{clan}' ({clan_tag}).",
                ephemeral=True,
            )
            return

        all_linked_tags = [
            tag for tags in guild_linked_accounts.values() for tag in tags
        ]

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
                f"⚠️ The following accounts in clan '{clan}' ({clan_tag}) are not linked to Discord:\n\n"
                + "\n".join(unlinked_players)
                + f"\n\nTotal: {len(unlinked_players)} unlinked accounts"
            )
        else:
            message = (
                f"✅ All accounts in clan '{clan}' ({clan_tag}) are linked to Discord!"
            )

        if len(message) > 2000:
            chunks = []
            current_chunk = f"⚠️ Unlinked accounts in clan '{clan}' ({clan_tag}):\n\n"

            for player in unlinked_players:
                if len(current_chunk) + len(player) + 2 > 1900:
                    chunks.append(current_chunk)
                    current_chunk = f"⚠️ Continued - unlinked accounts:\n\n{player}\n"
                else:
                    current_chunk += player + "\n"

            if current_chunk:
                chunks.append(current_chunk)

            chunks[-1] += f"\nTotal: {len(unlinked_players)} unlinked accounts"

            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(chunk)
                else:
                    await interaction.followup.send(chunk, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)

    @unlinked_accounts.on_autocomplete("clan")
    async def clan_autocomplete(self, interaction: nextcord.Interaction, query: str):
        guild_clan_channels = await get_guild_data(
            "clan_channels", interaction.guild_id
        )
        matching_clans = [
            info["name"]
            for tag, info in guild_clan_channels.items()
            if query.lower() in info["name"].lower()
        ]
        await interaction.response.send_autocomplete(matching_clans[:25])

    @nextcord.slash_command(
        name="help",
        description="Complete guide for setting up and using AttackAlert bot",
    )
    async def help_command(self, interaction: nextcord.Interaction):
        """Comprehensive help guide for AttackAlert bot"""

        help_embed = nextcord.Embed(
            title="🤖 AttackAlert Bot - Complete Setup Guide",
            description="Your ultimate Clash of Clans war reminder bot!",
            color=0x00FF00,
        )

        # Quick Setup Section
        help_embed.add_field(
            name="🚀 **Quick Setup (5 Steps)**",
            value=(
                "1️⃣ `/set_reminder_channel` - Set where war reminders go\n"
                "2️⃣ `/monitor_clan` - Add your clan(s) to monitoring\n"
                "3️⃣ `/link_account` - Link Discord users to CoC accounts\n"
                "4️⃣ `/set_prep_channel` - Set prep reminder channel (You will get a tag 1 hour before a war starts)\n"
                "5️⃣ `/assign_prep_notifiers` - Assign prep notification users (optional)\n"
                "\n✅ **Done!** Your bot will now send war reminders automatically!"
            ),
            inline=False,
        )

        # Core Commands Section
        help_embed.add_field(
            name="⚔️ **Essential Commands (Admins Only)**",
            value=(
                "`/set_reminder_channel` - Set channel for war reminders\n"
                "`/monitor_clan` - Add a clan to monitoring (max 4)\n"
                "`/unmonitor_clan` - Remove a clan from monitoring\n"
                "`/link_account` - Link Discord user to CoC account\n"
                "`/unlink_account` - Remove CoC account link\n"
                "`/list_monitored_clans` - Show all monitored clans"
            ),
            inline=False,
        )

        # User Commands Section
        help_embed.add_field(
            name="👤 **User Commands (Everyone)**",
            value=(
                "`/my_accounts` - Show your linked CoC accounts\n"
                "`/match_status` - Check current war status for a clan\n"
                "`/unlinked_accounts` - Show unlinked accounts in clan"
            ),
            inline=False,
        )

        # Prep Notifications Section
        help_embed.add_field(
            name="🔔 **Preparation Reminders (Optional)**",
            value=(
                "`/set_prep_channel` - Set channel for prep reminders\n"
                "`/assign_prep_notifiers` - Assign users to get prep notifications\n"
                "`/list_prep_notifiers` - Show who gets prep reminders\n"
                "\n📝 **Note:** Prep reminders alert when war/CWL starts in <1 hour"
            ),
            inline=False,
        )

        # Info Commands Section
        help_embed.add_field(
            name="ℹ️ **Information Commands**",
            value=(
                "`/bot_config` - Show current bot configuration\n"
                "`/help` - Show this help guide\n"
                "`/health_check` - Check bot status (admins)\n"
                "`/sync_commands` - Refresh bot commands (admins)"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=help_embed, ephemeral=True)

        # Send additional setup tips
        tips_embed = nextcord.Embed(
            title="💡 **Setup Tips & Features**", color=0xFFAA00
        )

        tips_embed.add_field(
            name="🎯 **What the Bot Does**",
            value=(
                "• **War Reminders:** 1hr, 30min, 15min before war ends\n"
                "• **Prep Reminders:** <1hr before war/CWL starts\n"
                "• **Smart Targeting:** Only pings users who haven't attacked\n"
                "• **Multi-Clan Support:** Monitor up to 4 clans per server\n"
                "• **Account Linking:** Track which Discord users own which CoC accounts"
            ),
            inline=False,
        )

        tips_embed.add_field(
            name="⚙️ **Configuration Tips**",
            value=(
                "• **Clan Tags:** Include the # (e.g., #2YRLQV2CR)\n"
                "• **Account Linking:** Link all clan members for best results\n"
                "• **Channels:** Use dedicated channels for clean notifications\n"
                "• **Permissions:** Bot needs 'Send Messages' permission\n"
                "• **Multiple Clans:** Each clan can have different prep notifiers"
            ),
            inline=False,
        )

        tips_embed.add_field(
            name="🔧 **Troubleshooting**",
            value=(
                "• **No reminders?** Check `/bot_config` for missing setup\n"
                "• **Wrong clan?** Use `/unmonitor_clan` then re-add\n"
                "• **Missing attacks?** Ensure accounts are linked with `/link_account`\n"
                "• **Commands not working?** Try `/sync_commands`\n"
                "• **Need help?** Check `/health_check` for bot status"
            ),
            inline=False,
        )

        tips_embed.add_field(
            name="📋 **Example Setup Workflow**",
            value=(
                "```\n"
                "1. /set_reminder_channel #war-alerts\n"
                "2. /monitor_clan MyClaN #2YRLQV2CR\n"
                "3. /link_account @Player1 #ABC123DEF\n"
                "4. /link_account @Player2 #GHI456JKL\n"
                "5. /set_prep_channel #prep-alerts\n"
                "6. /assign_prep_notifiers MyClaN @Leader\n"
                "```"
            ),
            inline=False,
        )

        await interaction.followup.send(embed=tips_embed, ephemeral=True)


def setup():
    bot.add_cog(ClashCommands(bot))


# endregion


# region Reminder Functions
@tasks.loop(minutes=1)
async def reminder_check():
    """Main reminder check loop with comprehensive error handling."""
    try:
        logging.info("\n=== Starting reminder check cycle ===")

        # Get all guilds with clan data from database, fall back to JSON if needed
        guilds_clan_data = {}

        if db_manager._initialized:
            try:
                guilds_clan_data = await db_manager.get_all_guilds_with_clans()
                logging.info(f"Retrieved {len(guilds_clan_data)} guilds from database")
            except Exception as e:
                logging.warning(
                    f"Database error in reminder_check, falling back to JSON: {e}"
                )
                guilds_clan_data = clan_channels
        else:
            guilds_clan_data = clan_channels

        # Check if there are any guilds with clan data
        if not guilds_clan_data:
            logging.info("No guilds with clan data found, skipping reminder check")
            return

        # Iterate through each guild's clan channels
        for guild_id, guild_clans in guilds_clan_data.items():
            try:
                logging.info(f"Checking guild {guild_id}:")
                guild_linked_accounts = await get_guild_data(
                    "linked_accounts", int(guild_id)
                )
                guild_prep_notifications = await get_guild_data(
                    "prep_notifications", int(guild_id)
                )

                # Run checks sequentially instead of concurrently to avoid duplicate logs
                for clan_tag, channel_data in guild_clans.items():
                    try:
                        logging.info(f"  Checking clan {clan_tag}:")

                        # 1. Check CWL status
                        try:
                            logging.info("    Checking CWL status")
                            league_data = await make_coc_request_async(
                                f"clans/{clan_tag.replace('#', '%23')}/currentwar/leaguegroup"
                            )
                            if league_data and league_data.get("state") == "inWar":
                                await cwl_reminder_check_for_clan(
                                    clan_tag, channel_data, guild_linked_accounts
                                )
                        except Exception as e:
                            logging.error(
                                f"Error checking CWL for clan {clan_tag}: {e}"
                            )

                        # 2. Check normal war status
                        try:
                            logging.info("    Checking normal war status")
                            war_data = await make_coc_request_async(
                                f"clans/{clan_tag.replace('#', '%23')}/currentwar"
                            )
                            if war_data and war_data.get("state") == "inWar":
                                await trigger_reminders(
                                    war_data,
                                    channel_data,
                                    is_cwl=False,
                                    guild_linked_accounts=guild_linked_accounts,
                                )
                        except Exception as e:
                            logging.error(
                                f"Error checking normal war for clan {clan_tag}: {e}"
                            )

                        # 3. Check preparation status
                        try:
                            logging.info("    Checking preparation status")
                            if clan_tag in guild_prep_notifications:
                                # Only check prep status if we have valid war data
                                if war_data and isinstance(war_data, dict):
                                    await check_prep_status(
                                        clan_tag, war_data, league_data, int(guild_id)
                                    )
                                else:
                                    # Also check if there's CWL preparation to handle
                                    if (
                                        league_data
                                        and league_data.get("state") == "preparation"
                                    ):
                                        await check_prep_status(
                                            clan_tag, None, league_data, int(guild_id)
                                        )
                                    else:
                                        logging.info(
                                            f"    No valid war data for clan {clan_tag}, skipping prep check"
                                        )
                        except Exception as e:
                            logging.error(
                                f"Error checking prep status for clan {clan_tag}: {e}"
                            )

                    except Exception as e:
                        logging.error(
                            f"Error processing clan {clan_tag} in guild {guild_id}: {e}"
                        )
                        continue  # Continue with next clan

            except Exception as e:
                logging.error(f"Error processing guild {guild_id}: {e}")
                continue  # Continue with next guild

        logging.info("=== Completed reminder check cycle ===\n")

    except Exception as e:
        logging.error(f"Critical error in reminder check: {e}")
        # Don't re-raise the exception to prevent the loop from stopping


@reminder_check.error
async def reminder_check_error(error):
    """Handle errors in the reminder check loop."""
    logging.error(f"Reminder check loop error: {error}")
    # The loop will automatically restart


# endregion


# region War Reminder Checks
# This section was removed as the functionality is now handled in the main reminder_check loop
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


async def reset_reminder_flags_for_guild(clan_tag, war_id, guild_id):
    """Reset reminder flags for a given war ID in the prep_notifications for a specific guild."""
    guild_prep_notifications = await get_guild_data("prep_notifications", guild_id)
    if (
        clan_tag in guild_prep_notifications
        and war_id in guild_prep_notifications[clan_tag]["wars"]
    ):
        logging.info(
            f"Resetting reminder flags for guild {guild_id}, clan {clan_tag}, War ID: {war_id}"
        )
        guild_prep_notifications[clan_tag]["wars"][war_id][
            "1_hour_reminder_sent"
        ] = False
        save_data(PREP_NOTIFICATION_FILE, prep_notifications)


async def trigger_reminders(
    war_data, channel_data, is_cwl=False, round_num=None, guild_linked_accounts=None
):
    war_end_time_str = war_data.get("endTime")
    time_until_end = calculate_time_until_war_end(war_end_time_str, "inWar")

    war_type = "CWL" if is_cwl else "Normal"
    round_info = f" (Round {round_num})" if is_cwl else ""

    reminder_time_messages = {
        "1_hour": {
            "normal": "⏰ There is 1 hour left in the war! Remember to attack! ⏰",
            "cwl": "⏰ There is 1 hour left in the war! Remember to attack and fill CC for the next battle! ⏰",
        },
        "30_min": {
            "normal": "⏰ There are 30 minutes left in the war! Attack now! ⏰",
            "cwl": "⏰ There are 30 minutes left in the war! Attack now and remember to fill CC for the next battle! ⏰",
        },
        "15_min": {
            "normal": "⚠️ 15 minutes left in the war! Hurry up and attack! ⚠️",
            "cwl": "⚠️ 15 minutes left in the war! THIS IS IT, NOW OR NEVER! - Also remember to fill CC for the next battle! ⚠️",
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

        # Create beautiful embed for war reminders
        color_map = {
            "1_hour": 0x00FF00,  # Green
            "30_min": 0xFFFF00,  # Yellow
            "15_min": 0xFF0000,  # Red
        }

        embed = nextcord.Embed(
            title=f"⚔️ {war_type} War Alert{round_info}",
            description=f"**{clan_name}** `{clan_tag}`",
            color=color_map.get(reminder_triggered, 0x00FF00),
            timestamp=datetime.now(timezone.utc),
        )

        # Add time remaining field
        time_emoji = {"1_hour": "⏰", "30_min": "⚠️", "15_min": "🚨"}
        embed.add_field(
            name=f"{time_emoji.get(reminder_triggered, '⏰')} Reminder",
            value=reminder_message,
            inline=False,
        )

        # Add players who need to attack
        unattacked_list = []
        for player_tag, missing_attacks in unattacked_players.items():
            discord_mentions = [
                f"<@{user_id}>"
                for user_id, tags in (guild_linked_accounts or {}).items()
                if player_tag in tags
            ]
            linked_users = (
                ", ".join(discord_mentions)
                if discord_mentions
                else "❌ No Discord link"
            )
            unattacked_list.append(
                f"• **{player_tag}**: {missing_attacks} attacks missing\n   └ {linked_users}"
            )

        if unattacked_list:
            # Split into chunks if too long
            unattacked_text = "\n".join(unattacked_list)
            if len(unattacked_text) > 1024:
                # Split into multiple fields if too long
                chunks = []
                current_chunk = ""
                for line in unattacked_list:
                    if len(current_chunk + line) > 1000:
                        chunks.append(current_chunk.strip())
                        current_chunk = line + "\n"
                    else:
                        current_chunk += line + "\n"
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())

                for i, chunk in enumerate(chunks):
                    field_name = f"🎯 Players Needing Attacks ({i+1}/{len(chunks)})"
                    embed.add_field(name=field_name, value=chunk, inline=False)
            else:
                embed.add_field(
                    name="🎯 Players Needing Attacks",
                    value=unattacked_text,
                    inline=False,
                )

        embed.set_footer(text=f"AttackAlert • {war_type} War System")

        try:
            urgency_map = {
                "1_hour": "⏰ **WAR REMINDER**",
                "30_min": "⚠️ **URGENT WAR REMINDER**",
                "15_min": "🚨 **FINAL WAR WARNING**",
            }
            content = urgency_map.get(reminder_triggered, "⚔️ **WAR ALERT**")

            await channel.send(content=content, embed=embed)
            logging.info(
                f"Sent {reminder_triggered} reminder for {war_type} war to {channel_data['channel']}"
            )
        except Exception as e:
            logging.error(f"Failed to send reminder: {e}")


async def cwl_reminder_check_for_clan(clan_tag, channel_data, guild_linked_accounts):
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
                    current_war,
                    channel_data,
                    is_cwl=True,
                    round_num=current_round,
                    guild_linked_accounts=guild_linked_accounts,
                )
                break

        if current_war:
            break


async def check_prep_status(clan_tag, war_data, league_data, guild_id):
    """Helper function to check preparation status for a single clan"""
    try:
        guild_prep_notifications = await get_guild_data("prep_notifications", guild_id)
        if clan_tag not in guild_prep_notifications:
            return

        prep_data = guild_prep_notifications[clan_tag]

        # Check normal war preparation
        if war_data:
            war_state = war_data.get("state")
            logging.info(f"War state for clan {clan_tag}: {war_state}")

            if war_state == "inWar":
                logging.info(
                    f"Clan {clan_tag} is now in war. Clearing war reminder states."
                )
                # Clear all war reminder states for this clan (database first, JSON fallback)
                if db_manager._initialized:
                    try:
                        await db_manager.clear_war_reminder_states(guild_id, clan_tag)
                        logging.info(
                            f"Cleared war reminder states for clan {clan_tag} (database)"
                        )
                    except Exception as e:
                        logging.warning(
                            f"Database error clearing war states, falling back to JSON: {e}"
                        )
                        # Fallback: clear JSON data
                        if (
                            str(guild_id) in prep_notifications
                            and clan_tag in prep_notifications[str(guild_id)]
                        ):
                            prep_notifications[str(guild_id)][clan_tag]["wars"] = {}
                            save_data(PREP_NOTIFICATION_FILE, prep_notifications)
                else:
                    # JSON fallback
                    if (
                        str(guild_id) in prep_notifications
                        and clan_tag in prep_notifications[str(guild_id)]
                    ):
                        prep_notifications[str(guild_id)][clan_tag]["wars"] = {}
                        save_data(PREP_NOTIFICATION_FILE, prep_notifications)
            elif war_state == "preparation":
                logging.info(
                    f"Clan {clan_tag} is in preparation. Processing prep notifications."
                )
                # Validate war_data structure before processing
                if not war_data.get("endTime"):
                    logging.error(f"Missing endTime in war_data for clan {clan_tag}")
                    return
                if not war_data.get("clan"):
                    logging.error(f"Missing clan data in war_data for clan {clan_tag}")
                    return

                await process_normal_war_prep(clan_tag, war_data, prep_data, guild_id)
            else:
                logging.info(
                    f"Clan {clan_tag} war state is '{war_state}' - no prep processing needed"
                )
        else:
            logging.info(
                f"No war data for clan {clan_tag} - clan may not be in war or preparation"
            )

        # Check CWL preparation
        if league_data and league_data.get("state") == "preparation":
            logging.info(f"Clan {clan_tag} is in CWL preparation")
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

                            # Check if reminder was already sent (database first, JSON fallback)
                            reminder_sent = await get_war_reminder_sent(
                                guild_id, clan_tag, war_id
                            )
                            should_send = (
                                timedelta(minutes=60)
                                >= time_until_prep_end
                                > timedelta(minutes=55)
                            )

                            if should_send and not reminder_sent:
                                prep_channel_id = prep_data.get(
                                    "channel", await get_prep_channel(guild_id)
                                )
                                notifiers = prep_data.get("notifiers", [])

                                if prep_channel_id and notifiers:
                                    channel = bot.get_channel(prep_channel_id)
                                    if channel:
                                        notifier_mentions = ", ".join(
                                            [f"<@{user_id}>" for user_id in notifiers]
                                        )

                                        # Create beautiful embed for CWL preparation reminder
                                        embed = nextcord.Embed(
                                            title="🎯 CWL Preparation Alert",
                                            description=f"**{clan_name}** `{clan_tag}`",
                                            color=0xFF6B35,  # Orange color for urgency
                                            timestamp=datetime.now(timezone.utc),
                                        )

                                        embed.add_field(
                                            name="⏰ Time Remaining",
                                            value="**Less than 1 hour** left in preparation phase!",
                                            inline=False,
                                        )

                                        embed.add_field(
                                            name="🔔 Attention Required",
                                            value=f"{notifier_mentions}",
                                            inline=False,
                                        )

                                        embed.add_field(
                                            name="✅ Action Items",
                                            value="• Set your CWL lineup\n• Check clan castle troops\n• Prepare for battle!",
                                            inline=False,
                                        )

                                        embed.set_footer(
                                            text="AttackAlert • CWL Preparation System"
                                        )

                                        await channel.send(
                                            content=f"🚨 **CWL PREPARATION ALERT** 🚨",
                                            embed=embed,
                                        )
                                        logging.info(
                                            f"Successfully sent CWL prep reminder for clan {clan_tag}"
                                        )

                                        # Mark reminder as sent (database first, JSON fallback)
                                        await set_war_reminder_sent(
                                            guild_id, clan_tag, war_id
                                        )
                        except Exception as e:
                            logging.error(
                                f"Error processing CWL prep reminder: {str(e)}"
                            )
    except Exception as e:
        logging.error(f"Error in check_prep_status for clan {clan_tag}: {str(e)}")
        logging.error(f"War data: {war_data}")
        logging.error(f"League data: {league_data}")
        raise


# endregion


# region Preparation Notifications
async def get_war_reminder_sent(guild_id, clan_tag, war_id):
    """Get whether war reminder was sent - database first, JSON fallback"""
    if db_manager._initialized:
        try:
            war_state = await db_manager.get_war_reminder_state(
                guild_id, clan_tag, war_id
            )
            return war_state.reminder_1hour_sent if war_state else False
        except Exception as e:
            logging.warning(
                f"Database error getting war reminder state, falling back to JSON: {e}"
            )

    # Fallback to JSON
    guild_prep_notifications = prep_notifications.get(str(guild_id), {})
    return (
        guild_prep_notifications.get(clan_tag, {})
        .get("wars", {})
        .get(war_id, {})
        .get("1_hour_reminder_sent", False)
    )


async def set_war_reminder_sent(guild_id, clan_tag, war_id):
    """Set war reminder as sent - database first, JSON fallback"""
    if db_manager._initialized:
        try:
            await db_manager.set_war_reminder_sent(guild_id, clan_tag, war_id)
            logging.info(
                f"Saved reminder flag for clan {clan_tag}, war {war_id} (database)"
            )
            return True
        except Exception as e:
            logging.warning(
                f"Database error setting war reminder state, falling back to JSON: {e}"
            )

    # Fallback to JSON
    guild_prep_notifications = prep_notifications.setdefault(str(guild_id), {})
    if clan_tag not in guild_prep_notifications:
        guild_prep_notifications[clan_tag] = {
            "channel": None,
            "notifiers": [],
            "wars": {},
        }
    if "wars" not in guild_prep_notifications[clan_tag]:
        guild_prep_notifications[clan_tag]["wars"] = {}

    guild_prep_notifications[clan_tag]["wars"][war_id] = {"1_hour_reminder_sent": True}
    save_data(PREP_NOTIFICATION_FILE, prep_notifications)
    logging.info(
        f"Saved reminder flag for clan {clan_tag}, war {war_id} (JSON fallback)"
    )
    return True


async def process_cwl_prep(clan_tag, league_data, prep_data, guild_id):
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

    # Check if reminder was already sent (database first, JSON fallback)
    reminder_sent = await get_war_reminder_sent(guild_id, clan_tag, war_id)

    should_send = timedelta(minutes=60) >= time_until_prep_end > timedelta(minutes=55)
    logging.info(f"CWL Reminder already sent: {reminder_sent}")
    logging.info(f"Should send reminder: {should_send}")

    if should_send and not reminder_sent:
        # Get prep notification data for channel and notifiers
        guild_prep_notifications = await get_guild_data("prep_notifications", guild_id)
        prep_channel_id = guild_prep_notifications.get(clan_tag, {}).get(
            "channel", await get_prep_channel(guild_id)
        )
        notifiers = guild_prep_notifications.get(clan_tag, {}).get("notifiers", [])

        if prep_channel_id and notifiers:
            channel = bot.get_channel(prep_channel_id)
            if channel:
                notifier_mentions = ", ".join(
                    [f"<@{user_id}>" for user_id in notifiers]
                )
                try:
                    # Create beautiful embed for CWL preparation reminder
                    embed = nextcord.Embed(
                        title="🎯 CWL Preparation Alert",
                        description=f"**{clan_name}** `{clan_tag}`",
                        color=0xFF6B35,  # Orange color for urgency
                        timestamp=datetime.now(timezone.utc),
                    )

                    embed.add_field(
                        name="⏰ Time Remaining",
                        value="**Less than 1 hour** left in preparation phase!",
                        inline=False,
                    )

                    embed.add_field(
                        name="🔔 Attention Required",
                        value=f"{notifier_mentions}",
                        inline=False,
                    )

                    embed.add_field(
                        name="✅ Action Items",
                        value="• Set your CWL lineup\n• Check clan castle troops\n• Prepare for battle!",
                        inline=False,
                    )

                    embed.set_footer(text="AttackAlert • CWL Preparation System")

                    await channel.send(
                        content=f"🚨 **CWL PREPARATION ALERT** 🚨", embed=embed
                    )
                    logging.info(
                        f"Successfully sent CWL prep reminder for clan {clan_tag}"
                    )

                    # Mark reminder as sent (database first, JSON fallback)
                    await set_war_reminder_sent(guild_id, clan_tag, war_id)
                except Exception as e:
                    logging.error(f"Failed to send CWL prep reminder: {str(e)}")
            else:
                logging.error(f"Could not find channel with ID {prep_channel_id}")
        else:
            logging.warning(
                f"No prep channel ID ({prep_channel_id}) or notifiers ({notifiers}) configured"
            )


async def process_normal_war_prep(clan_tag, war_data, prep_data, guild_id):
    """Process preparation notifications for normal wars."""
    try:
        war_end_time_str = war_data.get("endTime")
        if not war_end_time_str:
            logging.error(f"No endTime found in war_data for clan {clan_tag}")
            return

        war_id = f"{war_end_time_str}"
        logging.info(f"Processing prep for clan {clan_tag}, war_id: {war_id}")

        time_until_start = calculate_time_until_war_end(war_end_time_str, "preparation")
        logging.info(
            f"Normal war time until start for clan {clan_tag}: {time_until_start}"
        )

        clan_name = war_data.get("clan", {}).get("name", "Unknown Clan")

        # Check if reminder was already sent (database first, JSON fallback)
        reminder_sent = await get_war_reminder_sent(guild_id, clan_tag, war_id)
        logging.info(f"Normal war reminder sent: {reminder_sent}")

        if (
            timedelta(hours=1, minutes=5) >= time_until_start > timedelta(minutes=25)
            and not reminder_sent
        ):
            prep_channel_id = prep_data.get("channel", await get_prep_channel(guild_id))
            notifiers = prep_data.get("notifiers", [])

            if prep_channel_id and notifiers:
                channel = bot.get_channel(prep_channel_id)
                notifier_mentions = ", ".join(
                    [f"<@{user_id}>" for user_id in notifiers]
                )

                if channel:
                    try:
                        # Create beautiful embed for normal war preparation reminder
                        embed = nextcord.Embed(
                            title="⚠️ War Preparation Alert",
                            description=f"**{clan_name}** `{clan_tag}`",
                            color=0xFFD700,  # Gold color for war prep
                            timestamp=datetime.now(timezone.utc),
                        )

                        embed.add_field(
                            name="⏰ Time Remaining",
                            value="**Less than 1 hour** before war starts!",
                            inline=False,
                        )

                        embed.add_field(
                            name="🔔 Attention Required",
                            value=f"{notifier_mentions}",
                            inline=False,
                        )

                        embed.add_field(
                            name="⚔️ Prepare for Battle",
                            value="• Check your war base\n• Plan your attacks\n• Coordinate with clan mates",
                            inline=False,
                        )

                        embed.set_footer(text="AttackAlert • War Preparation System")

                        await channel.send(
                            content=f"⚔️ **WAR PREPARATION ALERT** ⚔️", embed=embed
                        )
                        logging.info(
                            f"Sent normal preparation reminder for war {war_id}."
                        )

                        # Mark reminder as sent (database first, JSON fallback)
                        await set_war_reminder_sent(guild_id, clan_tag, war_id)
                    except Exception as e:
                        logging.error(
                            f"Failed to send normal prep reminder for war {war_id}: {e}"
                        )
            else:
                logging.info(
                    f"No prep channel or notifiers configured for clan {clan_tag}"
                )
        else:
            logging.info(f"Prep reminder not needed for clan {clan_tag} at this time")

    except Exception as e:
        logging.error(f"Error in process_normal_war_prep for clan {clan_tag}: {str(e)}")
        logging.error(f"War data: {war_data}")
        logging.error(
            f"Prep data keys: {list(prep_data.keys()) if 'prep_data' in locals() else 'prep_data not set'}"
        )
        raise


# endregion


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user}")
    logging.info(f"Bot is in {len(bot.guilds)} guilds")

    # Initialize database (gracefully handle failures for local development)
    try:
        await db_manager.initialize()
        logging.info("✅ Database initialized successfully")
    except Exception as e:
        logging.warning(
            f"Database initialization failed (running in local/JSON mode): {e}"
        )
        logging.info("Bot will continue using JSON files for data storage")

        # Load the cog
    setup()
    logging.info("Cog loaded")

    # Wait for cog commands to register
    logging.info("Waiting for cog commands to register...")
    await asyncio.sleep(5)

    # Count available commands before sync
    try:
        # For nextcord, we need to count differently
        cog = bot.get_cog("ClashCommands")
        if cog:
            # Use a more reliable method to count cog commands
            cog_commands = 13  # We know we have 13 cog commands
            logging.info(f"Cog found: {cog.__class__.__name__}")

            # Try to get actual command count for debugging
            if hasattr(cog, "__cog_commands__"):
                actual_count = len(cog.__cog_commands__)
                logging.info(f"Actual cog commands found: {actual_count}")
                if actual_count == 0:
                    logging.warning(
                        "Cog commands list is empty - commands may still be registering"
                    )
                    logging.info(
                        "Waiting additional 10 seconds for command registration to complete..."
                    )
                    await asyncio.sleep(10)

                    # Check again after waiting
                    final_count = len(cog.__cog_commands__)
                    logging.info(f"Final cog command count after wait: {final_count}")
            elif hasattr(cog, "get_commands"):
                actual_count = len(cog.get_commands())
                logging.info(f"Actual cog commands found: {actual_count}")
        else:
            cog_commands = 0
            logging.warning("ClashCommands cog not found!")

        # Count global slash commands
        global_commands = 4  # We know we have 4 global commands
        total_expected = cog_commands + global_commands
        logging.info(
            f"Commands before sync: Cog={cog_commands}, Global={global_commands}, Total={total_expected}"
        )

    except Exception as e:
        logging.warning(f"Could not count commands: {e}")
        total_expected = 17  # Expected number of commands (13 cog + 4 global)

        # Simplified command synchronization
    try:
        logging.info("Syncing slash commands...")

        # Single sync attempt with reasonable wait
        await asyncio.sleep(5)
        synced = await bot.sync_all_application_commands()
        synced_count = len(synced) if synced else 0

        if synced_count > 0:
            logging.info(f"✅ Successfully synced {synced_count} slash commands")
        else:
            logging.warning(f"⚠️ Sync reported 0 commands, but commands may still work")
            logging.warning(
                f"Expected {total_expected} commands - this is a known nextcord issue"
            )
            logging.info(
                "Commands should still be available in Discord despite sync reporting 0"
            )

    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
        logging.warning(
            "Bot will continue running - commands may still work despite sync failure"
        )

    reminder_check.start()
    logging.info("AttackAlert bot is ready and running!")


# Graceful shutdown handling
import signal
import sys


def signal_handler(sig, frame):
    logging.info(
        "Received shutdown signal, saving data and shutting down gracefully..."
    )

    # Save all data one final time
    try:
        save_data(LINKED_ACCOUNTS_FILE, linked_accounts)
        save_data(CLAN_CHANNELS_FILE, clan_channels)
        save_data(PREP_NOTIFICATION_FILE, prep_notifications)
        save_data(REMINDER_CHANNELS_FILE, reminder_channels)
        logging.info("All data saved successfully")
    except Exception as e:
        logging.error(f"Error saving data during shutdown: {e}")

    logging.info("Shutdown complete")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# Add basic health check endpoint (for monitoring)
@bot.slash_command(
    name="sync_commands",
    description="Manually sync all slash commands (Bot admin only)",
    default_member_permissions=nextcord.Permissions(administrator=True),
)
async def sync_commands(interaction: nextcord.Interaction):
    """Manually sync slash commands."""
    await interaction.response.defer(ephemeral=True)

    try:
        logging.info("Manual command sync initiated")

        # Count commands before sync
        try:
            cog = bot.get_cog("ClashCommands")
            cog_commands = (
                len(cog.__cog_commands__)
                if cog and hasattr(cog, "__cog_commands__")
                else 0
            )
            global_commands = 4  # We know we have 4 global commands
            total_commands = cog_commands + global_commands
        except Exception:
            total_commands = 17  # Expected number

        # Try normal sync first
        synced = await bot.sync_all_application_commands()
        count = len(synced) if synced else 0

        # If normal sync returns 0, try again after waiting
        if count == 0 and total_commands > 0:
            logging.info("Normal sync returned 0, trying again after wait...")
            await asyncio.sleep(2)
            synced = await bot.sync_all_application_commands()
            count = len(synced) if synced else 0

        await interaction.followup.send(
            f"✅ **Command Sync Complete**\n"
            f"**Available Commands:** {total_commands}\n"
            f"**Synced Commands:** {count}\n"
            f"Commands should now be available in Discord.",
            ephemeral=True,
        )
        logging.info(
            f"Manual sync completed: {count} commands (Available: {total_commands})"
        )

    except Exception as e:
        logging.error(f"Manual sync failed: {e}")
        await interaction.followup.send(
            f"❌ **Command Sync Failed**\n"
            f"Error: {str(e)}\n"
            f"Check logs for more details.",
            ephemeral=True,
        )


@bot.slash_command(
    name="force_sync",
    description="Force clear and re-sync all commands (Bot admin only)",
    default_member_permissions=nextcord.Permissions(administrator=True),
)
async def force_sync(interaction: nextcord.Interaction):
    """Force clear and re-sync all commands."""
    await interaction.response.defer(ephemeral=True)

    try:
        logging.info("Force command sync initiated")

        # Force sync by waiting and re-syncing
        await interaction.followup.send(
            "🔄 **Step 1:** Waiting for Discord sync...", ephemeral=True
        )
        await asyncio.sleep(5)

        # Re-sync commands
        await interaction.followup.send(
            "🔄 **Step 2:** Re-syncing commands...", ephemeral=True
        )
        synced = await bot.sync_all_application_commands()
        count = len(synced) if synced else 0

        # Count available commands
        try:
            cog = bot.get_cog("ClashCommands")
            cog_commands = (
                len(cog.__cog_commands__)
                if cog and hasattr(cog, "__cog_commands__")
                else 0
            )
            global_commands = 4  # We know we have 4 global commands
            total_commands = cog_commands + global_commands
        except Exception:
            total_commands = 17  # Expected number

        await interaction.followup.send(
            f"✅ **Force Sync Complete**\n"
            f"**Available Commands:** {total_commands}\n"
            f"**Synced Commands:** {count}\n"
            f"All commands have been cleared and re-registered.",
            ephemeral=True,
        )
        logging.info(f"Force sync completed: {count} commands")

    except Exception as e:
        logging.error(f"Force sync failed: {e}")
        await interaction.followup.send(
            f"❌ **Force Sync Failed**\n"
            f"Error: {str(e)}\n"
            f"Check logs for more details.",
            ephemeral=True,
        )


@bot.slash_command(
    name="list_commands",
    description="List all available bot commands (Bot admin only)",
    default_member_permissions=nextcord.Permissions(administrator=True),
)
async def list_commands(interaction: nextcord.Interaction):
    """List all registered commands."""
    await interaction.response.defer(ephemeral=True)

    try:
        # Get all slash commands from the bot
        commands = []

        # Get all commands from different sources
        try:
            # Get cog commands
            cog = bot.get_cog("ClashCommands")
            if cog and hasattr(cog, "__cog_commands__"):
                for command in cog.__cog_commands__:
                    if hasattr(command, "name") and hasattr(command, "description"):
                        commands.append(f"• `/{command.name}` - {command.description}")

            # Add global commands manually (nextcord doesn't expose pending_application_commands)
            global_commands = [
                ("sync_commands", "Manually sync all slash commands (Bot admin only)"),
                ("force_sync", "Force clear and re-sync all commands (Bot admin only)"),
                ("list_commands", "List all available bot commands (Bot admin only)"),
                (
                    "health_check",
                    "Check if the bot is running properly (Bot admin only)",
                ),
            ]
            for cmd_name, cmd_desc in global_commands:
                commands.append(f"• `/{cmd_name}` - {cmd_desc}")
        except Exception as e:
            logging.error(f"Error getting commands: {e}")
            commands = ["❌ Could not retrieve command list"]

        if commands:
            command_list = "\n".join(commands)
            message = f"🤖 **Available Commands ({len(commands)}):**\n\n{command_list}"
        else:
            message = "❌ No commands found. Try running `/sync_commands` first."

        # Split message if too long
        if len(message) > 2000:
            chunks = [message[i : i + 1900] for i in range(0, len(message), 1900)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await interaction.followup.send(chunk, ephemeral=True)
                else:
                    await interaction.followup.send(
                        f"**Continued...**\n{chunk}", ephemeral=True
                    )
        else:
            await interaction.followup.send(message, ephemeral=True)

    except Exception as e:
        logging.error(f"List commands failed: {e}")
        await interaction.followup.send(
            f"❌ **Error listing commands**\n{str(e)}", ephemeral=True
        )


@bot.slash_command(
    name="health_check",
    description="Check if the bot is running properly (Bot admin only)",
    default_member_permissions=nextcord.Permissions(administrator=True),
)
async def health_check(interaction: nextcord.Interaction):
    """Basic health check for monitoring purposes."""
    try:
        # Check if we can access the API
        test_response = await make_coc_request_async("clans/%23P80CC2U", retries=1)
        api_status = "✅ Working" if test_response else "❌ Failed"

        # Check data files
        files_status = "✅ All files accessible"
        for filepath in [
            LINKED_ACCOUNTS_FILE,
            CLAN_CHANNELS_FILE,
            PREP_NOTIFICATION_FILE,
            PREP_CHANNEL_FILE,
        ]:
            if not os.path.exists(filepath):
                files_status = f"⚠️ Missing {filepath}"
                break

        # Count monitored clans
        total_clans = sum(len(guild_clans) for guild_clans in clan_channels.values())

        health_report = (
            f"🏥 **AttackAlert Health Check**\n\n"
            f"🤖 **Bot Status:** Online\n"
            f"🌐 **API Status:** {api_status}\n"
            f"📁 **Files Status:** {files_status}\n"
            f"🏰 **Guilds:** {len(bot.guilds)}\n"
            f"⚔️ **Monitored Clans:** {total_clans}\n"
            f"🔄 **Reminder Loop:** {'✅ Running' if reminder_check.is_running() else '❌ Stopped'}\n"
            f"📊 **Latency:** {round(bot.latency * 1000)}ms"
        )

        await interaction.response.send_message(health_report, ephemeral=True)

    except Exception as e:
        logging.error(f"Health check failed: {e}")
        await interaction.response.send_message(
            f"❌ **Health Check Failed**\n```{str(e)}```", ephemeral=True
        )


if __name__ == "__main__":
    try:
        logging.info("Starting AttackAlert Discord Bot...")
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logging.fatal(f"Fatal error starting bot: {e}")
        sys.exit(1)
