FAQ
===

General Questions
-----------------

Q: How do I invite AttackAlert to my server?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Contact the bot administrator for an invitation link. You'll need **Administrator** permissions in your Discord server to add the bot. Each Discord server operates independently with its own configuration and data.

Q: Is my server's data separate from other servers?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Yes! AttackAlert provides complete guild isolation. Your server's settings, clan monitoring, account links, and all data are completely separate from other Discord servers. No data is shared between servers.

Q: How many clans can my server monitor?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Each Discord server can monitor up to **4 clans simultaneously**. This limit ensures optimal performance and prevents API rate limiting.

Setup and Configuration
-----------------------

Q: How do I set up war reminders?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Follow these steps:

1. Set a reminder channel: ``/set_reminder_channel #your-channel``
2. Add clans to monitor: ``/monitor_clan "Clan Name" #CLANTAG``
3. Link Discord users to CoC accounts: ``/link_account @user #PLAYERTAG``
4. Test with: ``/match_status "Clan Name"``

Q: Why aren't my commands working?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Common solutions:

- **Check permissions**: Ensure you have Administrator permissions for setup commands
- **Sync commands**: Try ``/sync_commands`` (Administrator only)
- **Bot permissions**: Verify the bot can send messages in your channels
- **Re-invite**: If issues persist, re-invite the bot with proper permissions

Q: Can I monitor the same clan from multiple Discord servers?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: No. Each clan can only be monitored by **one Discord server** to prevent conflicts and ensure data integrity. The first server to add a clan gets exclusive monitoring rights.

War Monitoring
--------------

Q: What types of wars does AttackAlert support?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: AttackAlert supports:

- **Normal Clan Wars**: Regular 15v15, 20v20, 25v25, 30v30, 40v40, 50v50 wars
- **Clan War League (CWL)**: All league levels with round-by-round tracking
- **Preparation phases**: Both normal war prep and CWL lineup setting
- **Multi-phase tracking**: Preparation → War → Ended states

Q: When do reminders get sent?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: War reminders are sent at:

- **1 hour** before war ends (general encouragement)
- **30 minutes** before war ends (urgent reminder)  
- **15 minutes** before war ends (final warning)

**Smart targeting**: Only users who haven't completed their attacks are reminded.

Q: How does CWL monitoring work?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: CWL features include:

- **Round-by-round tracking**: Each battle is monitored separately
- **Preparation reminders**: Alerts when lineup setting begins
- **CC donation reminders**: Special reminders about clan castle prep
- **Multi-day support**: Tracks entire CWL season automatically

Account Management
------------------

Q: Can users link multiple Clash of Clans accounts?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Yes! Users can link multiple CoC accounts to their Discord profile. This is perfect for players who have multiple game accounts or play across different clans.

Q: Are account links shared between Discord servers?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: No. Account links are **server-specific**. If you're in multiple Discord servers with AttackAlert, you'll need to link your accounts separately in each server.

Q: How do I find unlinked clan members?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Use ``/unlinked_accounts "Clan Name"`` to see which clan members don't have linked Discord accounts. This helps identify who won't receive targeted reminders.

Technical Questions
-------------------

Q: What happens if the database goes down?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: AttackAlert uses a **hybrid storage system**:

- **Primary**: Database storage for better performance
- **Fallback**: Automatic JSON file backup during database issues  
- **Seamless operation**: Bot continues working even during database outages
- **No data loss**: All functionality remains available

Q: How often does the bot check for wars?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: AttackAlert checks war status **every minute** for:

- New war detection
- War state changes (prep → war → ended)
- Attack count updates
- CWL round progression

Q: Can I see bot health status?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Yes! Administrators can use ``/health_check`` to see:

- Database connectivity status
- Clash of Clans API response times
- Bot memory usage and performance
- Current storage mode (database/JSON)

Troubleshooting
---------------

Q: Reminders aren't being sent, what's wrong?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Check these common issues:

1. **Reminder channel set**: ``/set_reminder_channel #channel``
2. **Bot permissions**: Can send messages in the reminder channel
3. **Active war**: Clan must be in an active war state
4. **Account linking**: Users need linked accounts for targeted reminders
5. **Channel access**: Bot can view and send messages in the channel

Q: I'm getting "clan already monitored" errors?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: This means another Discord server is already monitoring that clan. Each clan can only be monitored by one server. You can:

- Choose a different clan to monitor
- Contact the other server to resolve the conflict
- Use ``/list_monitored_clans`` to see your current clans

Q: Bot says "database not available" but still works?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: This is normal! The bot automatically falls back to JSON file storage when the database is unavailable. All functionality continues working seamlessly.

Q: How do I report bugs or request features?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Contact the bot administrator or development team through the designated support channels. Include:

- Clear description of the issue
- Steps to reproduce the problem  
- Screenshots if applicable
- Server ID for debugging purposes

Advanced Features
-----------------

Q: What are preparation notifiers?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Preparation notifiers are specific users who receive alerts during:

- **CWL preparation**: When lineup setting begins
- **Normal war prep**: Before war starts
- **Special events**: Important clan activities

Set them up with: ``/assign_prep_notifiers "Clan Name" @User``

Q: Can I have different reminder channels for different clans?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: Currently, each Discord server has one reminder channel for all monitored clans. However, you can set a separate preparation channel using ``/set_prep_channel`` for prep-specific notifications.

Q: How do I migrate from an older version?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A: The bot automatically handles data migration. If you previously used a file-based version, your data will be automatically imported when you first run commands. No manual migration is needed.

