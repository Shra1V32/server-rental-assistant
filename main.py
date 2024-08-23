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
    GROUP_ID,
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
# Example: 7d -> 7 days, 5h -> 5 hours, 10m -> 10 minutes, 30s -> 30 seconds
# 1d2h -> 1 day 2 hours, 3h30m -> 3 hours 30 minutes
# Returns the duration in seconds
def parse_duration(duration_str):
    duration_str = duration_str.lower()
    total_seconds = 0
    current_number = ""
    for char in duration_str:
        if char.isdigit():
            current_number += char
        else:
            if char == "d":
                total_seconds += int(current_number) * 24 * 60 * 60
            elif char == "h":
                total_seconds += int(current_number) * 60 * 60
            elif char == "m":
                total_seconds += int(current_number) * 60
            elif char == "s":
                total_seconds += int(current_number)
            current_number = ""
    return total_seconds


# Helper function to reduce a user's plan
async def reduce_plan_helper(event, username, reduced_duration_seconds):
    cursor.execute("SELECT expiry_time FROM users WHERE username=?", (username,))
    result = cursor.fetchone()

    if result:
        expiry_time = result[0]
        if expiry_time - reduced_duration_seconds < int(time.time()):
            await event.respond(
                f"❌ Cannot reduce plan for user `{username}` below current time."
            )
            return

        new_expiry_time = expiry_time - reduced_duration_seconds

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
            f"🔄 User `{username}`'s plan reduced to `{new_expiry_date}`."
        )
    else:
        await event.respond(f"❌ User `{username}` not found.")


@client.on(events.NewMessage(pattern="/reduce_plan"))
async def reduce_plan(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    args = event.message.text.split()
    if len(args) < 3:
        await event.respond(
            "❓ Usage: /reduce_plan <username> <reduced_duration> \nFor example: `/reduce_plan john 7d`"
        )
        return

    username = args[1]
    reduced_duration_str = args[2]
    reduced_duration_seconds = parse_duration(reduced_duration_str)

    if username == "all":
        cursor.execute("SELECT username FROM users")
        usernames = cursor.fetchall()
        for row in usernames:
            await reduce_plan_helper(event, row[0], reduced_duration_seconds)
    else:
        await reduce_plan_helper(event, username, reduced_duration_seconds)


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
        f"{BE_NOTED_TEXT}"
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


# Command to list all users along with their expiry dates and remaining time
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

            remaining_time = expiry_date_ist - datetime.now(pytz.utc).astimezone(ist)
            remaining_time_str = ""
            if remaining_time.days > 0:
                remaining_time_str += f"{remaining_time.days} days, "
            remaining_time_str += f"{remaining_time.seconds // 3600} hours, "
            remaining_time_str += f"{(remaining_time.seconds // 60) % 60} minutes"

            response += f"✨ Username: `{username}`\n   Expiry Date: `{expiry_date_str}`\n   Remaining Time: `{remaining_time_str}`\n\n"
    else:
        response = "🔍 No users found."

    await event.respond(response)


# Periodic task to notify users of plan expiry
# We first notify in the group before 12 hours of expiry
# The GROUP_ID must be set in the .env file for this to work
async def notify_expiry():
    while True:
        now = int(time.time())
        twelve_hours_from_now = now + (12 * 60 * 60)  # 12 hours in seconds
        cursor.execute(
            "SELECT user_id, username FROM users WHERE expiry_time<=? AND expiry_time>? AND sent_expiry_notification=false",
            (twelve_hours_from_now, now),
        )
        expiring_users = cursor.fetchall()

        for _, username in expiring_users:
            cursor.execute(
                "UPDATE users SET sent_expiry_notification=true WHERE username=?",
                (username,),
            )
            conn.commit()

            expiry_time = cursor.execute(
                "SELECT expiry_time FROM users WHERE username=?", (username,)
            ).fetchone()[0]

            # Send a notification to the group, include the username and the remaining time
            remaining_time = datetime.fromtimestamp(expiry_time) - datetime.now()

            # Mention remaining time in human-readable format
            # Example: expire in 8 hours, 30 minutes
            remaining_time_str = ""
            if remaining_time.days > 0:
                remaining_time_str += f"{remaining_time.days} days, "
            remaining_time_str += f"{remaining_time.seconds // 3600} hours, "
            remaining_time_str += f"{(remaining_time.seconds // 60) % 60} minutes"

            message = (
                f"⏰ Plan for user `{username}` will expire in {remaining_time_str}."
            )
            if not GROUP_ID:
                print(
                    "Warning: GROUP_ID is not set in .env file. Skipping group notification."
                )
                await client.send_message(ADMIN_ID, message)
            else:
                try:
                    await client.send_message(GROUP_ID, message)
                except Exception as e:
                    # Send to admin if there is an error sending to the group
                    await client.send_message(
                        ADMIN_ID, f"❌ Error sending message: {e}"
                    )
                    await client.send_message(ADMIN_ID, message)
        await asyncio.sleep(60)  # Check every minute


# Handle button presses
@client.on(events.CallbackQuery())
async def handle_button(event):
    if event.data == b"cancel":
        username = event.data.decode().split()[1]
        prev_msg = (
            f"⚠️ Plan for user `{username}` has expired. Please take necessary action."
        )
        # Update is_expired to True
        cursor.execute("UPDATE users SET is_expired=true WHERE username=?", (username,))
        conn.commit()

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
