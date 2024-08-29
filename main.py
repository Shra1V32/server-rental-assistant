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
    username TEXT UNIQUE NOT NULL,
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


# Get /etc/passwd file data
def get_passwd_data():
    with open("/etc/passwd", "r") as f:
        passwd_data = f.readlines()
    return passwd_data


# Function to check if username exists in passwd file
def is_user_exists(username):
    passwd_data = get_passwd_data()
    for line in passwd_data:
        if line.startswith(username + ":"):
            return True
    return False


# Function to execute shell commands to create a user
def create_system_user(username, password):
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


# Function to parse time duration strings
# Example: 7d -> 7 days, 5h -> 5 hours, 10m -> 10 minutes, 30s -> 30 seconds
# 1d2h -> 1 day 2 hours, 3h30m -> 3 hours 30 minutes
# Returns the duration in seconds
def parse_duration(duration_str: str):
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


# Parse the duration seconds to human readable format
def parse_duration_to_human_readable(duration_seconds: int) -> str:
    duration_str = ""
    if duration_seconds > 0:
        if duration_seconds // (24 * 3600) > 0:
            duration_str += f"{duration_seconds // (24 * 3600)} days, "
            duration_seconds %= 24 * 3600
        if duration_seconds // 3600 > 0:
            duration_str += f"{duration_seconds // 3600} hours, "
            duration_seconds %= 3600
        if duration_seconds // 60 > 0:
            duration_str += f"{duration_seconds // 60} minutes, "
            duration_seconds %= 60
        if duration_seconds > 0:
            duration_str += f"{duration_seconds} seconds"
    else:
        duration_str = "Expired"
    return duration_str


# Helper function to reduce a user's plan
async def reduce_plan_helper(event, username, reduced_duration_seconds):
    cursor.execute("SELECT expiry_time FROM users WHERE username=?", (username,))
    result = cursor.fetchone()

    if result:
        expiry_time = result[0]
        new_expiry_time = expiry_time - reduced_duration_seconds

        if new_expiry_time < int(time.time()):
            await event.respond(
                f"❌ User `{username}` will already be expired with this duration."
            )
            return

        cursor.execute(
            """
        UPDATE users
        SET expiry_time=?
        WHERE username=?
        """,
            (new_expiry_time, username),
        )
        conn.commit()

        # Show expiry date in the human-readable user's timezone
        ist = pytz.timezone(TIME_ZONE)
        new_expiry_date = datetime.fromtimestamp(new_expiry_time, ist)
        day_suffix = get_day_suffix(new_expiry_date.day)
        new_expiry_date_str = new_expiry_date.strftime(
            f"%d{day_suffix} %B %Y, %I:%M %p IST"
        )

        # Print new expiry date, and duration reduced in human readable format
        await event.respond(
            f"🔄 User `{username}`'s plan reduced!"
            f"\nNew expiry date: `{new_expiry_date_str}`"
            f"\nDuration reduced by: `{parse_duration_to_human_readable(reduced_duration_seconds)}`"
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


# Helpful when you change the instances, and you want to sync with the database
# Once you run this command, it will create a user for each user in the database
# and set the expiry time to the database value, including the same passwords
@client.on(events.NewMessage(pattern="/sync_db"))
async def sync_db(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    cursor.execute("SELECT username, password, expiry_time FROM users")
    users = cursor.fetchall()

    for username, password, expiry_time in users:
        if not is_user_exists(username):
            try:
                create_system_user(username, password)
            except Exception as e:
                await event.respond(f"❌ Error creating user `{username}`: {e}")

            conn.commit()
            await client.send_message(
                ADMIN_ID,
                f"✅ User `{username}` created successfully with expiry time `{expiry_time}`.",
            )

    await event.respond("✅ Database synced with the system.")


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

    # Send acknowledgement message
    await event.respond("🔐 Creating user...")

    username = args[1]
    plan_duration_str = args[2]

    if is_user_exists(username):
        await event.respond(f"❌ User `{username}` already exists.")
        return

    plan_duration_seconds = parse_duration(plan_duration_str)
    password = generate_password()

    expiry_time = int(time.time()) + plan_duration_seconds

    try:
        create_system_user(username, password)
    except Exception as e:
        await event.respond(f"❌ Error creating user `{username}`: {e}")

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
        f"🔐 **Username:** `{username}`\n"
        f"🔑 **Password:** `{password}`\n"
        f"📅 **Expiry Date:** {expiry_date_str}\n"
        f"\n"
        f"🔗 **SSH Command:**\n"
        f"`{ssh_command}`\n"
    )

    if BE_NOTED_TEXT:
        message_str += f"**ℹ️ Notes:**\n{BE_NOTED_TEXT}\n"

    message_str += f"\n🔒 Your server is ready to use. Enjoy!"
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

    # Check if the user exists from the passwd file
    user_exists = is_user_exists(username)

    if not user_exists:
        await event.respond(f"❌ User `{username}` is not found in the system.")

        # Ask if to delete the user from the database
        await event.respond(
            f"❓ Do you want to delete user `{username}` from the database?",
            buttons=[
                [Button.inline("Yes", data=f"clean_db {username}")],
                [Button.inline("No", data="cancel")],
            ],
        )
        return

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

    # Send acknowledgement message
    await event.respond("🔄 Extending plan...")

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

        # Show expiry date in the human-readable user's timezone
        ist = pytz.timezone(TIME_ZONE)
        new_expiry_date = datetime.fromtimestamp(new_expiry_time, ist)
        day_suffix = get_day_suffix(new_expiry_date.day)
        new_expiry_date_str = new_expiry_date.strftime(
            f"%d{day_suffix} %B %Y, %I:%M %p IST"
        )

        # Print new expiry date, and duration extended in human readable format
        await event.respond(
            f"🔄 User `{username}`'s plan extended!"
            f"\nNew expiry date: `{new_expiry_date_str}`"
            f"\nDuration extended by: `{parse_duration_to_human_readable(additional_seconds)}`"
        )
    else:
        await event.respond(f"❌ User `{username}` not found.")


# Command to list all users along with their expiry dates and remaining time
@client.on(events.NewMessage(pattern="/list_users"))
async def list_users(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    cursor.execute("SELECT username, expiry_time, is_expired FROM users")
    users = cursor.fetchall()

    if users:
        response = f"👥 Total Users: {len(users)}\n\n"
        for username, expiry_time, is_expired in users:
            ist = pytz.timezone(TIME_ZONE)
            expiry_date_ist = datetime.fromtimestamp(expiry_time, ist)
            day_suffix = get_day_suffix(expiry_date_ist.day)
            expiry_date_str = expiry_date_ist.strftime(
                f"%d{day_suffix} %B %Y, %I:%M %p IST"
            )

            if not is_expired:

                remaining_time = expiry_date_ist - datetime.now(pytz.utc).astimezone(
                    ist
                )
                remaining_time_str = ""
                if remaining_time.days > 0:
                    remaining_time_str += f"{remaining_time.days} days, "
                remaining_time_str += f"{remaining_time.seconds // 3600} hours, "
                remaining_time_str += f"{(remaining_time.seconds // 60) % 60} minutes"

                response += f"✨ Username: `{username}`\n   Expiry Date: `{expiry_date_str}`\n   Remaining Time: `{remaining_time_str}`\n   Status: `Active`\n\n"

            else:  # If the user is expired, show the status as Expired
                elased_time = datetime.now(pytz.utc).astimezone(ist) - expiry_date_ist
                elased_time_str = ""
                if elased_time.days > 0:
                    elased_time_str += f"{elased_time.days} days, "
                elased_time_str += f"{elased_time.seconds // 3600} hours, "
                elased_time_str += f"{(elased_time.seconds // 60) % 60} minutes"

                response += f"❌ Username: `{username}`\n   Expiry Date: `{expiry_date_str}`\n   Elasped Time: `{elased_time_str}`\n   Status: `Expired`\n\n"
    else:
        response = "🔍 No users found."

    await event.respond(response)


# List the currently using/ connected users
@client.on(events.NewMessage(pattern="/who"))
async def list_connected_users(event):
    if not is_authorized(event.sender_id):
        await event.respond("❌ You are not authorized to use this command.")
        return

    connected_users = subprocess.run(
        ["w"], check=True, capture_output=True, text=True
    ).stdout

    # Send the connected users list as a table
    await event.respond(f"```\n{connected_users}\n```")


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

        # Check for expiring users and notify in the group
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

        # Check expired users and notify admin to take necessary action
        cursor.execute(
            "SELECT username FROM users WHERE expiry_time<=? AND is_expired=false",
            (now,),
        )
        expired_users = cursor.fetchall()

        for row in expired_users:
            username = row[0]
            cursor.execute(
                "UPDATE users SET is_expired=true WHERE username=?", (username,)
            )
            conn.commit()

            # Send expired message in the group
            if GROUP_ID:
                await client.send_message(
                    GROUP_ID, f"❌ Plan for user `{username}` has expired."
                )

            # Send action notification to the admin
            await client.send_message(
                ADMIN_ID,
                f"⚠️ Plan for user `{username}` has expired. Please take necessary action.",
                buttons=[
                    [Button.inline("Cancel", data=f"cancel {username}")],
                    [Button.inline("Delete User", data=f"delete_user {username}")],
                ],
            )

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
    elif event.data.startswith(b"clean_db"):
        username = event.data.decode().split()[1]
        cursor.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
        await event.edit(f"✅ User `{username}` deleted from the database.")

    else:
        await event.edit("❌ Invalid action.")


# Start the bot and the periodic task
async def main():
    await client.start()
    await client.run_until_disconnected()


loop = asyncio.get_event_loop()
loop.create_task(notify_expiry())
loop.run_until_complete(main())
