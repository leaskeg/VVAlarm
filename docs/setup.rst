Setup Guide
===========

Follow these steps to invite and configure VV-Alarm in your Discord server:

Step 1: Invite VV-Alarm
-----------------------
1. Click [this link](https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=277025614848&scope=bot+applications.commands).
2. Select the server you want to add VV-Alarm to.
3. Grant the required permissions and complete the setup.

Step 2: Configure VV-Alarm
--------------------------
1. **Set a Reminder Channel**:
   Use the `/set_reminder_channel` command to specify where reminders should be sent.

2. **Monitor a Clan**:
Use the `/monitor_clan` command to add a Clash of Clans clan to be monitored.
Example: /monitor_clan clan_name #CLANTAG

3. **Link Accounts**:
Allow admins to link player tags to Discord accounts with `/link_account`.
Example: /link_account @username #PLAYERTAG

Step 3: Verify Setup
--------------------
Use the `/match_status` command to check if everything is working. If the bot responds with clan details, you’re good to go!
