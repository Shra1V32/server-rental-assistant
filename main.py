import asyncio
import os
import random
import sqlite3
import string
import subprocess
import time
from datetime import datetime, timedelta

import pytz
from dotenv import load_dotenv
from telethon import Button, TelegramClient, events

from constants import (
    ADJECTIVES,
    ADMIN_ID,
    API_HASH,
    API_ID,
    BE_NOTED_TEXT,
    BOT_TOKEN,
    NOUNS,
    SSH_HOSTNAME,
    SSH_PORT,
    TIME_ZONE,
)

client = TelegramClient("server_plan_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# SQLite Database connection
conn = sqlite3.connect("server_plan.db")
cursor = conn.cursor()

# Create table if it doesn't exist
cursor.execute(
    """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password TEXT NOT NULL,
    expiry_time INTEGER NOT NULL,
    is_expired BOOLEAN DEFAULT False,
    sent_expiry_notification BOOLEAN DEFAULT False
)
"""
)
conn.commit()


# Function to check if the user is authorized
def is_authorized(user_id):
    return user_id == ADMIN_ID


def get_day_suffix(day):
    if 11 <= day <= 13:
        return "th"
    else:
        return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


# Function to generate a secure, memorable password
def generate_password():
    password = (
        random.choice(ADJECTIVES)
        + random.choice(NOUNS)
        + "".join(random.choices(string.digits, k=4))
    )
    return password


# Function to execute shell commands to create a user
def create_system_user(username, password):
    try:
        hashed_password = subprocess.run(
            ["openssl", "passwd", "-6", password],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            [
                "sudo",
                "useradd",
                "-m",
                "-s",
                "/bin/bash",
                "-p",
                hashed_password,
                username,
            ],
            check=True,
        )
        print(f"System user {username} created successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error creating user {username}: {e}")


# Function to parse time duration strings
def parse_duration(duration_str):
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    unit = duration_str[-1]
    value = int(duration_str[:-1])
    return value * time_units.get(unit, 0)


# Command to create a user and set plan expiry
@client.on(events.NewMessage(pattern="/create_user"))
async def create_user(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    args = event.message.text.split()
    if len(args) < 3:
        await event.respond(
            "❓ Usage: /create_user <username> <plan_duration> \nFor example: `/create_user john 7d`"
        )
        return

    username = args[1]
    plan_duration_str = args[2]
    plan_duration_seconds = parse_duration(plan_duration_str)
    password = generate_password()

    expiry_time = int(time.time()) + plan_duration_seconds

    create_system_user(username, password)

    cursor.execute(
        """
    INSERT INTO users (username, password, expiry_time)
    VALUES (?, ?, ?)
    """,
        (username, password, expiry_time),
    )
    conn.commit()

    # Show expiry date in the human-readable user's timezone, show notes, ssh command, etc.
    # Example for human readable time: 21st July 2024, 10:00 PM IST
    ist = pytz.timezone(TIME_ZONE)
    expiry_date_ist = datetime.fromtimestamp(expiry_time, ist)
    day_suffix = get_day_suffix(expiry_date_ist.day)
    expiry_date_str = expiry_date_ist.strftime(f"%d{day_suffix} %B %Y, %I:%M %p IST")

    ssh_command = "ssh " + username + "@" + SSH_HOSTNAME + " -p " + SSH_PORT

    message_str = (
        f"✅ User `{username}` created successfully.\n\n"
        f"🔐 Username: `{username}`\n"
        f"🔑 Password: `{password}`\n"
        f"📅 Expiry Date: {expiry_date_str}\n"
        f"\n"
        f"ℹ️ Notes:\n"
        f"- For SSH access, use the following command:\n"
        f"  `{ssh_command}`\n"
        f"\n"
        f"🔒 Your server is ready to use. Enjoy!"
    )
    await event.respond(message_str)


# Command to delete a user
@client.on(events.NewMessage(pattern="/delete_user"))
async def delete_user(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /delete_user <username>")
        return

    username = event.message.text.split()[1]
    cursor.execute("SELECT username FROM users WHERE username=?", (username,))
    result = cursor.fetchone()

    if result:
        await event.respond(f"🗑️ Deleting user `{username}`...")
        # remove all the running processes for the user
        subprocess.run(["sudo", "pkill", "-u", username], check=False)

        try:
            # delete the user from the system
            subprocess.run(["sudo", "userdel", "-r", username], check=True)
        except subprocess.CalledProcessError as e:
            await event.respond(f"❌ Error deleting user `{username}`: {e}")
            return
        cursor.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()

        await event.respond(f"✅ User `{username}` deleted.")
    else:
        await event.respond(f"❌ User `{username}` not found.")


# Command to extend a user's plan
@client.on(events.NewMessage(pattern="/extend_plan"))
async def extend_plan(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    args = event.message.text.split()
    if len(args) < 3:
        await event.respond(
            "❓ Usage: /extend_plan <username> <additional_duration>\nFor example: `/extend_plan john 5d`"
        )
        return

    username = args[1]
    additional_duration_str = args[2]
    additional_seconds = parse_duration(additional_duration_str)

    if username == "all":
        cursor.execute("SELECT username FROM users")
        usernames = cursor.fetchall()
        for row in usernames:
            await extend_plan_helper(event, row[0], additional_seconds)
    else:
        await extend_plan_helper(event, username, additional_seconds)


# Helper function to extend a user's plan
async def extend_plan_helper(event, username, additional_seconds):
    cursor.execute("SELECT expiry_time FROM users WHERE username=?", (username,))
    result = cursor.fetchone()

    if result:
        expiry_time = result[0]
        new_expiry_time = expiry_time + additional_seconds

        cursor.execute(
            """
        UPDATE users
        SET expiry_time=?
        WHERE username=?
        """,
            (new_expiry_time, username),
        )
        conn.commit()

        new_expiry_date = datetime.fromtimestamp(new_expiry_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        await event.respond(
            f"🔄 User `{username}`'s plan extended to `{new_expiry_date}`."
        )
    else:
        await event.respond(f"❌ User `{username}` not found.")


# Command to list all users along with their expiry dates
@client.on(events.NewMessage(pattern="/list_users"))
async def list_users(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    cursor.execute("SELECT username, expiry_time FROM users")
    users = cursor.fetchall()

    if users:
        response = "👥 Users:\n"
        for username, expiry_time in users:
            ist = pytz.timezone(TIME_ZONE)
            expiry_date_ist = datetime.fromtimestamp(expiry_time, ist)
            day_suffix = get_day_suffix(expiry_date_ist.day)
            expiry_date_str = expiry_date_ist.strftime(
                f"%d{day_suffix} %B %Y, %I:%M %p IST"
            )

            response += (
                f"✨ Username: `{username}`\n   Expiry Date: `{expiry_date_str}`\n\n"
            )
    else:
        response = "🔍 No users found."

    await event.respond(response)


# Periodic task to notify users of plan expiry
async def notify_expiry():
    while True:
        now = int(time.time())
        cursor.execute(
            "SELECT user_id, username FROM users WHERE expiry_time<=?", (now,)
        )
        expired_users = cursor.fetchall()

        for _, username in expired_users:
            # Check the database if is_expired is False
            cursor.execute(
                "SELECT sent_expiry_notification FROM users WHERE username=?",
                (username,),
            )
            result = cursor.fetchone()
            if result and not result[0]:  # If the user has not been notified
                cursor.execute(
                    "UPDATE users SET sent_expiry_notification=1 WHERE username=?",
                    (username,),
                )
                conn.commit()

                # Send a notification to the admin, include the start time, end time, and username
                # Add a button to delete the user from the database & server
                await client.send_message(
                    ADMIN_ID,
                    f"⚠️ Plan for user `{username}` has expired. Please take necessary action.",
                    buttons=[
                        [
                            Button.inline(
                                "Delete user", data=f"delete_user {username}"
                            ),
                            Button.inline("Cancel", data=f"cancel {username}"),
                        ],
                    ],
                )
            # subprocess.run(['sudo', 'userdel', '-r', username], check=True)
            # cursor.execute('DELETE FROM users WHERE username=?', (username,))
            # conn.commit()

        await asyncio.sleep(60)  # Check every minute


# Handle button presses
@client.on(events.CallbackQuery())
async def handle_button(event):
    if event.data == b"cancel":
        username = event.data.decode().split()[1]
        prev_msg = (
            f"⚠️ Plan for user `{username}` has expired. Please take necessary action."
        )

        await event.edit(prev_msg + "\n\n" + "🚫 Action canceled.")
    elif event.data.startswith(b"delete_user"):
        username = event.data.decode().split()[1]
        prev_msg = (
            f"⚠️ Plan for user `{username}` has expired. Please take necessary action."
        )
        await client.send_message(ADMIN_ID, f"🗑️ Deleting user `{username}`...")
        subprocess.run(["sudo", "pkill", "-u", username], check=False)
        try:
            subprocess.run(["sudo", "userdel", "-r", username], check=True)
        except subprocess.CalledProcessError as e:
            await event.edit(
                prev_msg + "\n\n" + f"❌ Error deleting user `{username}`: {e}"
            )
            return
        cursor.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
        await event.edit(prev_msg + "\n\n" + f"✅ User `{username}` deleted.")

    else:
        await event.edit("❌ Invalid action.")


# Start the bot and the periodic task
async def main():
    await client.start()
    await client.run_until_disconnected()


loop = asyncio.get_event_loop()
loop.create_task(notify_expiry())
loop.run_until_complete(main())
