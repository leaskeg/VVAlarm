# AttackAlert Discord Bot

A comprehensive Discord bot for Clash of Clans war monitoring and reminders. Supports multiple Discord servers with guild-specific data isolation, hybrid database/JSON storage, and advanced war tracking features.

## 🌟 Features

### War Monitoring
- **Normal War Tracking**: Automatic detection and monitoring of clan wars
- **CWL (Clan War League) Support**: Full CWL tracking with round-by-round monitoring
- **Multi-Phase Tracking**: Preparation, war, and ended states
- **Real-time Updates**: Minute-by-minute monitoring with automatic status checks
- **4 Clan Limit**: Each Discord server can monitor up to 4 clans simultaneously

### Reminder System
- **Timed Reminders**: 1-hour, 30-minute, and 15-minute war reminders
- **Preparation Alerts**: Notifications for war preparation phases
- **CWL Preparation**: Special reminders for CWL lineup setting
- **Targeted Notifications**: Only reminds players who haven't attacked
- **Smart Messaging**: Different messages for normal wars vs CWL

### Account Management
- **Discord-CoC Linking**: Link Clash of Clans accounts to Discord users
- **Multi-Account Support**: Users can link multiple CoC accounts
- **Unlinked Account Detection**: Identify clan members without Discord links
- **Guild-Specific Data**: Each Discord server has its own account data

### Security & Multi-Server Support
- **Guild Isolation**: Complete data separation between Discord servers
- **Clan Conflict Prevention**: Prevents multiple servers from monitoring the same clan
- **Admin Controls**: All management commands require administrator permissions
- **Hybrid Data Storage**: Database-first with JSON fallback for reliability

## 🛠️ Installation

### Prerequisites
- Python 3.8 or higher
- Discord Bot Token
- Clash of Clans API Token
- MySQL Database (optional - bot works with JSON files as fallback)

### Quick Setup with Deploy Script

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd VVAlarm
   ```

2. **Run the deployment script**
   ```bash
   python deploy.py
   ```
   This script will:
   - Check Python version
   - Install dependencies
   - Set up environment variables
   - Create necessary directories
   - Validate configuration

### Manual Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**
   - Copy `env.example` to `.env`
   - Edit `.env` with your tokens:
   ```
   DISCORD_BOT_TOKEN=your_discord_bot_token_here
   COC_API_TOKEN=your_clash_of_clans_api_token_here
   DATABASE_URL=mysql+aiomysql://user:password@host:port/database  # Optional
   LOG_LEVEL=INFO  # Optional: DEBUG, INFO, WARNING, ERROR
   ```

3. **Run the bot**
   ```bash
   python VV-Alarm.py
   ```

## 🔧 Configuration

### Getting Discord Bot Token
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section
4. Create a bot and copy the token
5. Enable necessary intents (Server Members Intent, Message Content Intent)

### Getting Clash of Clans API Token
1. Visit [Clash of Clans Developer Site](https://developer.clashofclans.com/)
2. Create an account and login
3. Create a new API key
4. Use your server's IP address (or 0.0.0.0 for development)

### Database Setup (Optional)
- The bot supports MySQL databases for better performance and reliability
- If no database is configured, the bot will use JSON files
- Database provides better concurrent access and data integrity
- Set `DATABASE_URL` in your `.env` file to enable database mode

### Bot Permissions
The bot requires the following Discord permissions:
- Send Messages
- Use Slash Commands
- Read Message History
- Mention Everyone (for reminders)
- View Channels

## 📋 Commands

### Administrative Commands
All administrative commands require **Administrator** permissions in Discord.

#### Initial Setup
- `/set_reminder_channel <channel>` - Set channel for war reminders
- `/set_prep_channel <channel>` - Set channel for preparation reminders

#### Clan Management
- `/monitor_clan <clan_name> <clan_tag>` - Add a clan to monitoring (max 4 per server)
- `/unmonitor_clan <clan>` - Remove a clan from monitoring
- `/list_monitored_clans` - Show all monitored clans for this server

#### Account Management
- `/link_account <discord_user> <player_tag>` - Link a CoC account to a Discord user
- `/unlink_account <discord_user> <player_tag>` - Remove a CoC account link
- `/unlinked_accounts <clan>` - Show clan members without Discord links

#### Preparation Notifications
- `/assign_prep_notifiers <clan> <user>` - Assign users to receive prep reminders
- `/list_prep_notifiers` - Show all prep notification assignments

#### Server Management
- `/bot_config` - Show current bot configuration for this server

#### Bot Administration (Bot Admin Only)
- `/sync_commands` - Manually sync all slash commands
- `/force_sync` - Force clear and re-sync all commands
- `/list_commands` - List all available bot commands
- `/health_check` - Check if the bot is running properly

### Public Commands
- `/match_status <clan>` - Check current war status for a clan
- `/my_accounts` - Show your linked Clash of Clans accounts

## 🔄 How It Works

### War Detection
1. Bot checks every minute for war status changes
2. Detects both normal wars and CWL battles
3. Tracks preparation, war, and ended phases
4. Monitors up to 4 clans per Discord server simultaneously

### Reminder Logic
- **1 Hour**: General reminder with attack encouragement
- **30 Minutes**: Urgent reminder to attack
- **15 Minutes**: Final warning with maximum urgency
- **CWL Special**: Additional reminders about CC donations for next battle

### Data Storage
- **Hybrid Approach**: Database first, JSON fallback
- **Guild-specific data**: Each Discord server has separate data
- **Automatic fallback**: If database fails, uses JSON files seamlessly
- **Data integrity**: Validation and conflict resolution for clan monitoring
- **Persistent states**: Reminder states saved across bot restarts

### Clan Monitoring Limits
- **4 Clan Maximum**: Each Discord server can monitor up to 4 clans
- **Conflict Prevention**: Same clan cannot be monitored by multiple servers
- **First-come basis**: Clan ownership assigned to first server that adds it

## 🛡️ Security Features

### Guild Isolation
- Each Discord server has completely separate data
- Account links are server-specific
- Clan monitoring is isolated per server
- No data sharing between Discord servers

### Clan Conflict Prevention
- Prevents multiple servers from monitoring the same clan
- Clear warnings about potential conflicts
- First-come-first-served clan ownership
- Automatic conflict detection and prevention

### Permission Controls
- All setup commands require Administrator permissions
- Public commands limited to information display
- Ephemeral responses for sensitive administrative information
- Role-based access control

## 📊 Monitoring

### War States Supported
- `GROUP_NOT_FOUND` - Clan not in any war
- `NOT_IN_WAR` - Clan exists but no active war
- `PREPARATION` - War preparation phase
- `WAR` - Active war phase
- `ENDED` - War completed

### CWL Phases
- `preparation` - CWL preparation period
- `inWar` - Active CWL rounds
- `ended` - CWL season completed

### Data Storage Modes
- **Database Mode**: MySQL database for production use
- **JSON Mode**: Local file storage for development/backup
- **Hybrid Mode**: Database primary, JSON fallback (recommended)

## 🔧 Troubleshooting

### Common Issues

1. **Bot not responding to commands**
   - Check bot permissions in Discord
   - Verify bot is online and connected
   - Run `/sync_commands` to manually sync slash commands
   - Use `/health_check` to verify bot status

2. **API errors**
   - Verify CoC API token is valid
   - Check clan tags are correct (include #)
   - Ensure API token IP whitelist is correct
   - Check API rate limits

3. **Reminders not working**
   - Confirm reminder channel is set with `/set_reminder_channel`
   - Check clan is properly monitored with `/list_monitored_clans`
   - Verify bot has send message permissions in the channel
   - Use `/bot_config` to check server configuration

4. **Data not saving**
   - Check file permissions in bot directory
   - Ensure sufficient disk space
   - Verify bot has write access to JSON files
   - Check database connection if using database mode

5. **Command sync issues**
   - Use `/sync_commands` for manual sync
   - Try `/force_sync` for complete command refresh
   - Check bot permissions in Discord server
   - Verify bot has slash command permissions

### Logs and Debugging
- Bot logs to both console and rotating log files in `logs/` directory
- Set `LOG_LEVEL=DEBUG` in `.env` for detailed logging
- Check `logs/vv-alarm.log` for error details
- Use UTF-8 encoding for proper character handling

### File Structure
```
VVAlarm/
├── VV-Alarm.py              # Main bot file
├── deploy.py                # Deployment helper script
├── requirements.txt         # Python dependencies
├── env.example             # Environment variables template
├── linked_accounts.json    # Account links (auto-created)
├── clan_channels.json      # Clan monitoring data (auto-created)
├── prep_notifications.json # Prep notification settings (auto-created)
├── prep_channel.json       # Prep channels (auto-created)
├── logs/                   # Log files directory
└── README.md              # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly with both database and JSON modes
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [nextcord](https://github.com/nextcord/nextcord) Discord library
- Powered by [Clash of Clans API](https://developer.clashofclans.com/)
- Uses SQLAlchemy for database operations
- Created for the Clash of Clans community

## 📞 Support

For support, please:
1. Check the troubleshooting section above
2. Use the `/health_check` command to diagnose issues
3. Review the issues on GitHub
4. Create a new issue with detailed information and logs

## 🔄 Version History

### Current Features
- Hybrid database/JSON storage system
- 4 clan monitoring limit per server
- Comprehensive command set with autocomplete
- Advanced error handling and logging
- Multi-guild support with data isolation
- Automatic command synchronization
- Health monitoring and diagnostics

---

**Note**: This bot is not affiliated with Supercell or Clash of Clans. It's a community-created tool for Discord servers. 