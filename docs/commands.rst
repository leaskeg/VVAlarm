Commands
========

AttackAlert provides a comprehensive set of slash commands organized by permission level and functionality. All commands are server-specific and operate within guild-isolated environments.

Administrative Commands
-----------------------

**Permission Required:** Administrator permissions in Discord

Initial Setup Commands
~~~~~~~~~~~~~~~~~~~~~~

**/set_reminder_channel <channel>**
  Sets the channel where war attack reminders will be sent.
  
  - **Required for**: War reminder functionality
  - **Example**: ``/set_reminder_channel #war-reminders``

**/set_prep_channel <channel>**
  Sets the channel where preparation phase reminders will be sent.
  
  - **Optional**: Only needed if you want prep notifications
  - **Example**: ``/set_prep_channel #prep-alerts``

Clan Management Commands
~~~~~~~~~~~~~~~~~~~~~~~~

**/monitor_clan <clan_name> <clan_tag>**
  Adds a Clash of Clans clan to monitoring for this Discord server.
  
  - **Limit**: 4 clans per Discord server maximum
  - **Conflict Prevention**: Same clan cannot be monitored by multiple servers
  - **Example**: ``/monitor_clan "Elite Warriors" #2Y9L9Q2J``

**/unmonitor_clan <clan>**
  Removes a clan from monitoring for this Discord server.
  
  - **Autocomplete**: Available clans shown in dropdown
  - **Effect**: Stops all war monitoring and reminders for that clan
  - **Example**: ``/unmonitor_clan "Elite Warriors"``

**/list_monitored_clans**
  Shows all clans currently being monitored by this Discord server.
  
  - **Information shown**: Clan names, tags, associated channels, member counts
  - **Server-specific**: Only shows clans monitored by your server

Account Management Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**/link_account <discord_user> <player_tag>**
  Links a Clash of Clans player account to a Discord user.
  
  - **Multi-account support**: Users can have multiple linked accounts
  - **Server-specific**: Links only apply to current Discord server
  - **Example**: ``/link_account @PlayerName #PLAYERTAG123``

**/unlink_account <discord_user> <player_tag>**
  Removes a linked Clash of Clans account from a Discord user.
  
  - **Selective removal**: Can remove specific accounts while keeping others
  - **Example**: ``/unlink_account @PlayerName #PLAYERTAG123``

**/unlinked_accounts <clan>**
  Shows clan members who don't have linked Discord accounts.
  
  - **Helps identify**: Members who won't receive targeted reminders
  - **Autocomplete**: Available monitored clans shown in dropdown
  - **Example**: ``/unlinked_accounts "Elite Warriors"``

Preparation Notification Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**/assign_prep_notifiers <clan> <user>**
  Assigns Discord users to receive preparation phase reminders.
  
  - **Use cases**: CWL lineup setting, war preparation alerts
  - **Multiple assignments**: Can assign different users per clan
  - **Example**: ``/assign_prep_notifiers "Elite Warriors" @ClanLeader``

**/list_prep_notifiers**
  Shows all preparation notification assignments for this server.
  
  - **Organized by clan**: Clear overview of who gets notified for each clan
  - **Server-specific**: Only shows assignments for current server

Server Configuration Commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**/bot_config**
  Displays comprehensive bot configuration for this Discord server.
  
  - **Shows**: Reminder channels, monitored clans, linked accounts, prep settings
  - **Database status**: Current storage mode (database/JSON)
  - **Statistics**: Member counts, monitoring status

Bot Administration Commands
---------------------------

**Permission Required:** Bot Administrator (restricted to bot owner/designated admins)

**/sync_commands**
  Manually synchronizes all slash commands with Discord.
  
  - **Use when**: Commands not appearing or updating properly
  - **Safe to use**: Won't affect bot functionality

**/force_sync**
  Forces a complete clear and re-sync of all commands.
  
  - **Use when**: Major command issues or after bot updates
  - **More aggressive**: Clears existing commands first

**/list_commands**
  Lists all available bot commands with descriptions.
  
  - **Debugging tool**: Verify command registration status
  - **Admin reference**: Complete command overview

**/health_check**
  Performs comprehensive bot health diagnostics.
  
  - **Checks**: Database connectivity, API status, memory usage
  - **Response time**: Bot latency and performance metrics
  - **Storage status**: Current data storage mode and health

Public Commands
---------------

**Permission Required:** None (available to all server members)

**/match_status <clan>**
  Displays current war status for a monitored clan.
  
  - **Information shown**: War state, time remaining, attack counts
  - **CWL support**: Shows current round and preparation status
  - **Autocomplete**: Available monitored clans shown in dropdown
  - **Example**: ``/match_status "Elite Warriors"``

**/my_accounts**
  Shows your linked Clash of Clans accounts for this Discord server.
  
  - **Personal information**: Only shows your own linked accounts
  - **Server-specific**: Only accounts linked to current server
  - **Privacy focused**: Other users cannot see your account information

**/help**
  Provides comprehensive setup and usage guide.
  
  - **Interactive guide**: Step-by-step bot configuration
  - **Command examples**: Real usage scenarios
  - **Troubleshooting**: Common issues and solutions

Command Features
----------------

**Autocomplete Support**
Many commands provide intelligent autocomplete:

- **Clan selection**: Shows only monitored clans for your server
- **User selection**: Discord user picker with search
- **Smart filtering**: Results filtered based on context

**Error Handling**
Comprehensive error messages for common issues:

- **Permission errors**: Clear explanation of required permissions
- **Limit exceeded**: Helpful guidance when hitting clan limits
- **Conflict detection**: Warns about clan monitoring conflicts
- **API issues**: Graceful handling of Clash of Clans API problems

**Guild Isolation**
Every command operates within server-specific boundaries:

- **Data separation**: No cross-server data sharing
- **Independent configuration**: Each server has its own settings
- **Privacy protection**: Server data is completely isolated

**Hybrid Operation**
Commands work seamlessly across storage modes:

- **Database-first**: Preferred mode for better performance
- **JSON fallback**: Automatic fallback during database issues
- **Transparent operation**: Users don't need to know current storage mode






