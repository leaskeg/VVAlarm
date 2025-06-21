Setup Guide
===========

Follow these steps to invite and configure AttackAlert in your Discord server. Each Discord server operates independently with its own configuration and data.

Step 1: Invite AttackAlert
--------------------------

**Prerequisites**
- You must have **Administrator** permissions in your Discord server
- The bot requires specific permissions to function properly

**Invitation Process**
1. Use the bot invitation link (provided by bot administrator)
2. Select your Discord server from the dropdown
3. Ensure all required permissions are granted:
   - Send Messages
   - Use Slash Commands
   - Read Message History
   - Mention Everyone (for reminders)
   - View Channels
4. Complete the OAuth authorization

Step 2: Configure AttackAlert
-----------------------------

**Initial Setup (Required)**

1. **Set Reminder Channel**
   Configure where war reminders will be sent:
   
   ``/set_reminder_channel #your-war-channel``

2. **Set Preparation Channel** (Optional)
   Configure where preparation reminders will be sent:
   
   ``/set_prep_channel #your-prep-channel``

**Clan Monitoring Setup**

3. **Add Clans to Monitor** (Up to 4 per server)
   Add Clash of Clans clans for war monitoring:
   
   ``/monitor_clan YourClanName #CLANTAG``
   
   **Important Notes:**
   - Each Discord server can monitor up to 4 clans
   - Same clan cannot be monitored by multiple Discord servers
   - Clan tags must start with # (e.g., #2Y9L9Q2J)
   - First server to add a clan gets exclusive monitoring rights

4. **Link Discord Users to CoC Accounts**
   Connect Discord users to their Clash of Clans accounts:
   
   ``/link_account @DiscordUser #PLAYERTAG``
   
   **Benefits of Account Linking:**
   - Targeted reminders only for users who haven't attacked
   - Better tracking of member participation
   - Identify unlinked clan members
   - Guild-specific account management

**Advanced Configuration**

5. **Set Up Preparation Notifiers** (Optional)
   Assign specific users to receive preparation reminders:
   
   ``/assign_prep_notifiers YourClanName @User1``
   
   These users will be notified when:
   - CWL preparation phase begins
   - Normal war preparation starts
   - Lineup changes are needed

6. **View Configuration**
   Check your server's current settings:
   
   ``/bot_config``

Step 3: Verify Setup
--------------------

**Test War Monitoring**
Use the match status command to verify clan monitoring:

``/match_status YourClanName``

**Expected Responses:**
- If working: Detailed war status with current state
- If clan not found: Check clan tag spelling and API connectivity
- If no wars: "No active war" message (this is normal)

**Check Account Links**
Verify user account linking:

``/my_accounts`` - Shows your linked accounts
``/unlinked_accounts YourClanName`` - Shows clan members without Discord links

**Review Configuration**
Confirm all settings are correct:

``/list_monitored_clans`` - Shows all clans being monitored by your server
``/list_prep_notifiers`` - Shows all preparation notification assignments

Step 4: Understanding Limitations
---------------------------------

**Per-Server Limits:**
- Maximum 4 clans can be monitored per Discord server
- Account links are specific to each Discord server
- Configuration settings are isolated per server

**Clan Monitoring Conflicts:**
- Each clan can only be monitored by one Discord server
- If another server is already monitoring your clan, you'll get an error
- Contact the other server to resolve conflicts or choose different clans

**Permission Requirements:**
- All setup commands require **Administrator** permissions
- Regular users can only use information commands (/match_status, /my_accounts)
- Bot admin commands are restricted to bot administrators only

Troubleshooting
---------------

**Common Issues:**

*Commands not working:*
- Ensure bot has proper permissions
- Try ``/sync_commands`` (Administrator only)
- Re-invite bot with correct permissions

*Clan not being monitored:*
- Check if clan tag is correct (must start with #)
- Verify clan exists in Clash of Clans
- Ensure you haven't exceeded 4 clan limit
- Check if another server is monitoring the same clan

*Reminders not working:*
- Confirm reminder channel is set with ``/set_reminder_channel``
- Ensure bot has permission to send messages in the channel
- Check if clan is in an active war state
- Verify account linking for targeted reminders

*Database connectivity issues:*
- Bot automatically falls back to JSON file storage
- Functionality remains available during database outages
- Check logs for connectivity messages
