import asyncio
import os
import random
import sqlite3
import string
import subprocess
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv
from telethon import TelegramClient, events

load_dotenv()

api_id = os.getenv("API_ID")
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")
admin_id = int(os.getenv("ADMIN_ID"))

client = TelegramClient("server_plan_bot", api_id, api_hash).start(bot_token=bot_token)

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
    expiry_time INTEGER NOT NULL
)
"""
)
conn.commit()


# Function to check if the user is authorized
def is_authorized(user_id):
    return user_id == admin_id


# Function to generate a secure, memorable password
def generate_password():
    adjectives = [
        "crazy",
        "sunny",
        "happy",
        "wild",
        "quick",
        "witty",
        "jolly",
        "zany",
        "lazy",
    ]
    nouns = [
        "cat",
        "evening",
        "river",
        "breeze",
        "mountain",
        "ocean",
        "sun",
        "moon",
        "tree",
    ]
    password = (
        random.choice(adjectives)
        + random.choice(nouns)
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
            ["sudo", "useradd", "-m", "-p", hashed_password, username], check=True
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

    expiry_date = datetime.fromtimestamp(expiry_time).strftime("%Y-%m-%d %H:%M:%S")
    await event.respond(
        f"✨ User `{username}` created with password `{password}`.\n📅 Plan expires on `{expiry_date}`."
    )


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
        subprocess.run(["sudo", "userdel", "-r", username], check=True)

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
            expiry_date = datetime.fromtimestamp(expiry_time).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            response += f"✨ `{username}`: `{expiry_date}`\n"
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

        for user_id, username in expired_users:
            await client.send_message(
                user_id,
                f"⏰ Your plan has expired, `{username}`! Please renew soon. 😊",
            )
            # subprocess.run(['sudo', 'userdel', '-r', username], check=True)
            # cursor.execute('DELETE FROM users WHERE username=?', (username,))
            # conn.commit()

        await asyncio.sleep(60)


# Start the bot and the periodic task
async def main():
    await client.start()
    await client.run_until_disconnected()


loop = asyncio.get_event_loop()
loop.create_task(notify_expiry())
loop.run_until_complete(main())
