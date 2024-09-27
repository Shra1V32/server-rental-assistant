import asyncio
import random
import re
import sqlite3
import string
import subprocess
import time
import uuid
from datetime import datetime

import aiohttp
import pytz
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

# --- Database Setup ---
conn = sqlite3.connect("server_plan.db")
cursor = conn.cursor()


def create_table(table_name, schema):
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({schema})")
    conn.commit()


create_table(
    "users",
    """
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE DEFAULT NULL,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    creation_time INTEGER DEFAULT (cast(strftime('%s', 'now') as int)),
    expiry_time INTEGER NOT NULL,
    is_expired BOOLEAN DEFAULT False,
    tg_username TEXT DEFAULT NULL,
    tg_first_name TEXT DEFAULT NULL,
    tg_last_name TEXT DEFAULT NULL,
    tg_user_id INTEGER DEFAULT NULL,
    sent_expiry_notification BOOLEAN DEFAULT False
    """,
)

create_table(
    "payments",
    """
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    payment_date INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
    """,
)


# --- Authorization ---
def is_authorized_user(user_id):
    return user_id == ADMIN_ID


def is_authorized_group(group_id):
    return group_id == GROUP_ID


# --- Utility Functions ---
def get_day_suffix(day):
    if 11 <= day <= 13:
        return "th"
    else:
        return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def generate_password():
    return (
        random.choice(ADJECTIVES)
        + random.choice(NOUNS)
        + "".join(random.choices(string.digits, k=4))
    )


def get_passwd_data():
    with open("/etc/passwd", "r") as f:
        return f.readlines()


def is_user_exists(username):
    return any(line.startswith(username + ":") for line in get_passwd_data())


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


def parse_duration_to_human_readable(duration_seconds: int) -> str:
    if duration_seconds <= 0:
        return "Expired"

    duration_str = ""
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
    return duration_str


def get_date_str(epoch: int):
    ist = pytz.timezone(TIME_ZONE)
    date = datetime.fromtimestamp(epoch, ist)
    day_suffix = get_day_suffix(date.day)
    return date.strftime(f"%d{day_suffix} %B %Y, %I:%M %p IST")


async def get_exchange_rate(from_currency, to_currency):
    url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data["rates"][to_currency]


# --- System User Management ---
def create_system_user(username, password):
    hashed_password = subprocess.run(
        ["openssl", "passwd", "-6", password],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["sudo", "useradd", "-m", "-s", "/bin/bash", "-p", hashed_password, username],
        check=True,
    )
    print(f"System user {username} created successfully.")


async def delete_system_user(username, event):
    await client.send_message(ADMIN_ID, f"🗑️ Deleting user `{username}`...")
    subprocess.run(["sudo", "pkill", "-u", username], check=False)
    try:
        subprocess.run(["sudo", "userdel", "-r", username], check=True)
    except subprocess.CalledProcessError as e:
        await event.edit(f"❌ Error deleting user `{username}`: {e}")
        return
    cursor.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    await event.respond(f"✅ User `{username}` deleted.")


# --- Plan Management ---
async def modify_plan_duration(
    event, username, duration_change_seconds, action="reduced"
):
    cursor.execute("SELECT expiry_time FROM users WHERE username=?", (username,))
    result = cursor.fetchone()

    if not result:
        await event.respond(f"❌ User `{username}` not found.")
        return

    expiry_time = result[0]
    new_expiry_time = expiry_time + duration_change_seconds

    if new_expiry_time < int(time.time()) and action == "reduced":
        await event.respond(
            f"❌ User `{username}` will already be expired with this duration."
        )
        return

    cursor.execute(
        "UPDATE users SET expiry_time=? WHERE username=?", (new_expiry_time, username)
    )
    conn.commit()

    new_expiry_date_str = get_date_str(new_expiry_time)
    duration_change_str = parse_duration_to_human_readable(abs(duration_change_seconds))

    await event.respond(
        f"🔄 User `{username}`'s plan {action}!"
        f"\nNew expiry date: `{new_expiry_date_str}`"
        f"\nDuration {action} by: `{duration_change_str}`"
    )


async def extend_plan_helper(
    event, username, additional_seconds, send_notification=True
):
    await modify_plan_duration(event, username, additional_seconds, action="extended")
    cursor.execute(
        """
        UPDATE users
        SET sent_expiry_notification = false, 
            is_expired = false 
        WHERE username = ?;
        """,
        (username,),
    )
    conn.commit()


async def reduce_plan_helper(
    event, username, reduced_duration_seconds, send_notification=True
):
    await modify_plan_duration(
        event, username, -reduced_duration_seconds, action="reduced"
    )


# --- Payment Management ---
async def process_payment(event, username, amount_str, currency):
    if currency == "USD":
        try:
            amount = float(amount_str)
            exchange_rate = await get_exchange_rate("USD", "INR")
            amount_inr = amount * exchange_rate
        except (ValueError, KeyError):
            await event.respond("❌ Invalid amount or currency.")
            return
    elif currency == "INR":
        try:
            amount_inr = float(amount_str)
        except ValueError:
            await event.respond("❌ Invalid amount.")
            return
    else:
        await event.respond("❌ Invalid currency. Only INR and USD are supported.")
        return

    payment_date = int(time.time())

    cursor.execute(
        """
    INSERT INTO payments (user_id, amount, currency, payment_date)
    VALUES ((SELECT user_id FROM users WHERE username=?), ?, ?, ?)
    """,
        (username, amount_inr, "INR", payment_date),
    )
    conn.commit()
    return amount_inr


async def record_transaction(event, username, amount_str, currency, transaction_type):
    amount_inr = await process_payment(event, username, amount_str, currency)
    if amount_inr is None:
        return  # Error occurred during processing

    if transaction_type == "debit":
        amount_inr = -amount_inr

    await event.respond(
        f"✅ Amount `{amount_inr:.2f} INR` {transaction_type}ed from user `{username}`."
    )


# --- Decorators ---
def authorized_user(func):
    async def wrapper(event, *args, **kwargs):
        if not is_authorized_user(event.sender_id):
            await event.respond("❌ You are not authorized to use this command.")
            return
        return await func(event, *args, **kwargs)

    return wrapper


# --- Telegram Bot Commands ---


# /reduce_plan command
@client.on(events.NewMessage(pattern="/reduce_plan"))
@authorized_user
async def reduce_plan(event):

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
            await reduce_plan_helper(
                event, row[0], reduced_duration_seconds, send_notification=False
            )

        cursor.execute("SELECT username, expiry_time FROM users")
        users = cursor.fetchall()
        response = "🔄 All users' plans reduced!\n\n"
        response += "\n".join(
            [
                f"👤 User `{username}`\n   New expiry date: `{get_date_str(expiry_time)}`"
                for username, expiry_time in users
            ]
        )
        await event.respond(response)
    else:
        await reduce_plan_helper(event, username, reduced_duration_seconds)


# /sync_db command
@client.on(events.NewMessage(pattern="/sync_db"))
@authorized_user
async def sync_db(event):

    cursor.execute("SELECT username, password, expiry_time FROM users")
    users = cursor.fetchall()

    for username, password, expiry_time in users:
        if not is_user_exists(username):
            try:
                create_system_user(username, password)
            except Exception as e:
                await event.respond(f"❌ Error creating user `{username}`: {e}")
                continue

            await client.send_message(
                ADMIN_ID,
                f"✅ User `{username}` created successfully with expiry time `{expiry_time}`.",
            )

    await event.respond("✅ Database synced with the system.")


# /create_user command
@client.on(events.NewMessage(pattern="/create_user"))
@authorized_user
async def create_user(event):

    BOT_USERNAME = await client.get_me()

    args = event.message.text.split()
    if len(args) < 4:
        await event.respond(
            "❓ Usage: /create_user <username> <plan_duration> <amount> <currency (INR/USD)> \nFor example: `/create_user john 7d 500 INR`"
        )
        return

    await event.respond("🔐 Creating user...")

    username = args[1]
    plan_duration_str = args[2]
    amount_str = args[3]
    currency = args[4].upper()

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
        return

    expiry_date_str = get_date_str(expiry_time)
    ssh_command = f"ssh {username}@{SSH_HOSTNAME} -p {SSH_PORT}"

    message_str = (
        f"✅ User `{username}` created successfully.\n\n"
        f"🔐 **Username:** `{username}`\n"
        f"📅 **Expiry Date:** {expiry_date_str}\n"
        f"\n"
        f"🔗 **SSH Command:**\n"
        f"`{ssh_command}`\n"
        f"\n"
        f"🔑 **Password:** Please click the button below to get your password.\n\n"
    )

    if BE_NOTED_TEXT:
        message_str += f"**ℹ️ Notes:**\n{BE_NOTED_TEXT}\n"

    message_str += f"\n🔒 Your server is ready to use. Enjoy!"

    user_uuid = str(uuid.uuid4())
    password_url = f"https://t.me/{BOT_USERNAME.username}?start={user_uuid}"

    payment_date = int(time.time())

    cursor.execute(
        """
    INSERT INTO users (uuid, username, password, expiry_time)
    VALUES (?, ?, ?, ?)
    """,
        (user_uuid, username, password, expiry_time),
    )

    await client.send_message(
        event.chat_id,
        message_str,
        buttons=[[Button.url("Get Password", password_url)]],
    )

    amount_inr = await process_payment(event, username, amount_str, currency)
    if amount_inr is None:
        return  # Error occurred during processing

    message_str = (
        f"🔐 **Username:** `{username}`\n"
        f"🔑 **Password:** `{password}`\n"
        f"📅 **Expiry Date:** {expiry_date_str}\n"
        f"💰 **Amount:** `{amount_inr:.2f} INR`\n"
        f"📅 **Payment Date:** {get_date_str(payment_date)}\n"
    )

    await client.send_message(ADMIN_ID, message_str)


# /debit and /credit commands
@client.on(events.NewMessage(pattern="/debit"))
@authorized_user
async def debit_amount(event):

    args = event.message.text.split()
    if len(args) < 3:
        await event.respond(
            "❓ Usage: /debit <username> <amount> <currency>\nFor example: `/debit john 500 INR`"
        )
        return

    username = args[1]
    amount_str = args[2]
    currency = args[3].upper()

    await record_transaction(event, username, amount_str, currency, "debit")


@client.on(events.NewMessage(pattern="/credit"))
@authorized_user
async def credit_amount(event):

    args = event.message.text.split()
    if len(args) < 3:
        await event.respond(
            "❓ Usage: /credit <username> <amount> <currency>\nFor example: `/credit john 500 INR`"
        )
        return

    username = args[1]
    amount_str = args[2]
    currency = args[3].upper()

    await record_transaction(event, username, amount_str, currency, "credit")


# /help command
@client.on(events.NewMessage(pattern="/help"))
@authorized_user
async def help_command(event):

    help_text = """

    🔐 **Admin Commands:**

    - `/create_user <username> <plan_duration> <amount> <currency>`: Create a user with a plan duration and amount.
    - `/reduce_plan <username> <reduced_duration>`: Reduce the plan duration for a user.
    - `/sync_db`: Sync the database with the system.
    - `/debit <username> <amount> <currency>`: Debit the amount from the user.
    - `/credit <username> <amount> <currency>`: Credit the amount to the user.
    - `/earnings`: Show the total earnings.
    - `/delete_user <username>`: Delete a user.
    - `/extend_plan <username> <additional_duration> [amount] [currency]`: Extend a user's plan.
    - `/payment_history <username>`: Show the payment history for a user.
    - `/clear_user <username>`: Clear the Telegram username and user id for a user.
    - `/list_users`: List all users along with their expiry dates and remaining time.
    - `/who`: List the currently connected users.
    """

    await event.respond(help_text)


# /earnings command
@client.on(events.NewMessage(pattern="/earnings"))
@authorized_user
async def show_earnings(event):

    cursor.execute("SELECT SUM(amount) FROM payments")
    total_earnings = cursor.fetchone()[0] or 0

    await event.respond(f"💰 **Total Earnings:** `{total_earnings:.2f} INR`")


# /delete_user command
@client.on(events.NewMessage(pattern="/delete_user"))
@authorized_user
async def delete_user_command(event):

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /delete_user <username>")
        return

    username = event.message.text.split()[1]
    cursor.execute("SELECT username FROM users WHERE username=?", (username,))
    result = cursor.fetchone()

    user_exists = is_user_exists(username)

    if not user_exists:
        await event.respond(f"❌ User `{username}` is not found in the system.")

        await event.respond(
            f"❓ Do you want to delete user `{username}` from the database?",
            buttons=[
                [Button.inline("Yes", data=f"clean_db {username}")],
                [Button.inline("No", data="cancel")],
            ],
        )
        return

    if result:
        await delete_system_user(username, event)
    else:
        await event.respond(f"❌ User `{username}` not found.")


# /extend_plan command
@client.on(events.NewMessage(pattern="/extend_plan"))
@authorized_user
async def extend_plan(event):

    args = event.message.text.split()
    if len(args) < 3:
        await event.respond(
            "❓ Usage: /extend_plan <username> <additional_duration> [amount] [currency]\nFor example: `/extend_plan john 5d 500 INR`"
        )
        return

    await event.respond("🔄 Extending plan...")

    username = args[1]
    additional_duration_str = args[2]
    additional_seconds = parse_duration(additional_duration_str)

    amount_inr = None
    if len(args) >= 5:
        amount_str = args[3]
        currency = args[4].upper()
        amount_inr = await process_payment(event, username, amount_str, currency)
        if amount_inr is None:
            return

    if username == "all":
        cursor.execute("SELECT username FROM users")
        usernames = cursor.fetchall()
        for row in usernames:
            await extend_plan_helper(
                event, row[0], additional_seconds, send_notification=False
            )

        cursor.execute("SELECT username, expiry_time FROM users")
        users = cursor.fetchall()
        response = "🔄 All users' plans extended!\n\n"
        response += "\n".join(
            [
                f"👤 User `{username}`\n   New expiry date: `{get_date_str(expiry_time)}`"
                for username, expiry_time in users
            ]
        )
        await event.respond(response)
    else:
        await extend_plan_helper(event, username, additional_seconds)

    if amount_inr is not None:
        await event.respond(
            f"✅ Amount `{amount_inr:.2f} INR` credited to user `{username}`."
        )


# /payment_history command
@client.on(events.NewMessage(pattern="/payment_history"))
@authorized_user
async def payment_history(event):

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /payment_history <username>")
        return

    username = event.message.text.split()[1]
    cursor.execute(
        """
        SELECT amount, currency, payment_date
        FROM payments
        WHERE user_id = (SELECT user_id FROM users WHERE username = ?)
        ORDER BY payment_date DESC
        """,
        (username,),
    )
    payments = cursor.fetchall()

    if payments:
        response = f"💳 Payment History for `{username}`:\n\n"
        for amount, currency, payment_date in payments:
            payment_date_str = get_date_str(payment_date)
            response += f"💰 Amount: `{amount:.2f} {currency}`\n📅 Date: `{payment_date_str}`\n\n"
    else:
        response = f"🔍 No payment history found for `{username}`."

    await event.respond(response)


# /list_users command
@client.on(events.NewMessage(pattern="/list_users"))
@authorized_user
async def list_users(event):

    cursor.execute(
        "SELECT username, tg_user_id, tg_first_name, tg_last_name, expiry_time, is_expired FROM users"
    )
    users = cursor.fetchall()

    if not users:
        await event.respond("🔍 No users found.")
        return

    response = f"👥 Total Users: {len(users)}\n\n"
    ist = pytz.timezone(TIME_ZONE)

    for (
        username,
        tg_user_id,
        tg_user_first_name,
        tg_user_last_name,
        expiry_time,
        is_expired,
    ) in users:
        expiry_date_ist = datetime.fromtimestamp(expiry_time, ist)
        expiry_date_str = get_date_str(expiry_time)

        if not is_expired:
            remaining_time = expiry_date_ist - datetime.now(pytz.utc).astimezone(ist)
            remaining_time_str = ""
            if remaining_time.days > 0:
                remaining_time_str += f"{remaining_time.days} days, "
            remaining_time_str += f"{remaining_time.seconds // 3600} hours, "
            remaining_time_str += f"{(remaining_time.seconds // 60) % 60} minutes"

            tg_user_id = str(tg_user_id)

            if tg_user_id and tg_user_first_name and tg_user_last_name:
                tg_tag = f"[{tg_user_first_name} {tg_user_last_name}](tg://user?id={tg_user_id})"
            elif tg_user_id and tg_user_first_name:
                tg_tag = f"[{tg_user_first_name}](tg://user?id={tg_user_id})"
            else:
                tg_tag = tg_user_first_name if tg_user_first_name else "Not set"

            response += (
                f"✨ Username: `{username}`\n"
                f"   Telegram: {tg_tag}\n"
                f"   Expiry Date: `{expiry_date_str}`\n"
                f"   Remaining Time: `{remaining_time_str}`\n"
                f"   Status: `Active`\n\n"
            )

        else:
            elased_time = datetime.now(pytz.utc).astimezone(ist) - expiry_date_ist
            elased_time_str = ""
            if elased_time.days > 0:
                elased_time_str += f"{elased_time.days} days, "
            elased_time_str += f"{elased_time.seconds // 3600} hours, "
            elased_time_str += f"{(elased_time.seconds // 60) % 60} minutes"

            response += (
                f"❌ Username: `{username}`\n"
                f"   Telegram: [{tg_user_first_name}](tg://user?id={tg_user_id})\n"
                f"   Expiry Date: `{expiry_date_str}`\n"
                f"   Elapsed Time: `{elased_time_str}`\n"
                f"   Status: `Expired`\n\n"
            )

    await event.respond(response)

# /broadcast command
@client.on(events.NewMessage(pattern="/broadcast"))
@authorized_user
async def broadcast(event):
    
        if len(event.message.text.split()) < 2:
            await event.respond("❓ Usage: /broadcast <message>")
            return
    
        message = event.message.text.split(" ", 1)[1]
    
        cursor.execute("SELECT tg_user_id FROM users")
        users = cursor.fetchall()
    
        for user_id in users:
            try:
                await client.send_message(user_id[0], message)
            except:
                pass
    
        await event.respond(f"✅ Broadcasted message to {len(users)} users.")

# /clear_user command
@client.on(events.NewMessage(pattern="/clear_user"))
@authorized_user
async def clear_user(event):

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /clear_user <username>")
        return

    username = event.message.text.split()[1]
    cursor.execute(
        "UPDATE users SET tg_username=NULL, tg_user_id=NULL, tg_first_name=NULL, tg_last_name=NULL WHERE username=?",
        (username,),
    )
    conn.commit()

    await event.respond(
        f"✅ Cleared Telegram username and user id for user `{username}`."
    )


# /who command
@client.on(events.NewMessage(pattern="/who"))
@authorized_user
async def list_connected_users(event):

    await send_connected_users(event)


async def send_connected_users(event):
    connected_users = await asyncio.create_subprocess_shell(
        "w", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await connected_users.communicate()
    connected_users = stdout.decode()

    try:
        await event.edit(
            f"```\n{connected_users}\n```",
            buttons=[Button.inline("Refresh", data="refresh_connected_users")],
        )
    except:
        await event.respond(
            f"```\n{connected_users}\n```",
            buttons=[Button.inline("Refresh", data="refresh_connected_users")],
        )


@client.on(events.CallbackQuery(data="refresh_connected_users"))
async def refresh_connected_users(event):
    await send_connected_users(event)


# /start command
@client.on(events.NewMessage(pattern="/start"))
async def start_command(event):
    if len(event.message.text.split()) <= 1:
        return

    user_uuid = event.message.text.split()[1]

    cursor.execute(
        "SELECT username, password, tg_user_id FROM users WHERE uuid=?",
        (user_uuid,),
    )

    result = cursor.fetchone()
    if not result:
        await event.respond("❌ Invalid or expired link.")
        return

    username, password, tg_user_id = result

    user_id = event.sender_id
    new_tg_username = event.sender.username
    user_first_name = event.sender.first_name
    user_last_name = event.sender.last_name

    if tg_user_id is None:
        if new_tg_username is None:
            new_tg_username = user_id

        cursor.execute(
            "UPDATE users SET tg_username=?, tg_user_id=?, tg_first_name=?, tg_last_name=? WHERE username=?",
            (
                new_tg_username,
                user_id,
                user_first_name,
                user_last_name,
                username,
            ),
        )
        conn.commit()

        # Tag the user for future refs
        msg = f"[{user_first_name}](tg://user?id={user_id})\n\n"

        await event.respond(
            msg + f"🔑 **Username:** `{username}`\n🔒 **Password:** `{password}`"
        )
        await client.send_message(
            ADMIN_ID,
            f"🔑 Password sent to user [{user_first_name}](tg://user?id={user_id}).",
        )
    else:
        # Tag the user for future refs
        msg = f"[{user_first_name}](tg://user?id={user_id})\n\n"
        
        if user_id == tg_user_id:
            await event.respond(
                msg + f"🔑 **Username:** `{username}`\n🔒 **Password:** `{password}`"
            )
        else:
            await event.respond(
                "❌ You are not authorized to get the password for this user."
            )


# --- Background Tasks ---
async def notify_expiry():
    while True:
        now = int(time.time())
        twelve_hours_from_now = now + (12 * 60 * 60)
        cursor.execute(
            "SELECT tg_user_id, tg_first_name, username FROM users WHERE expiry_time<=? AND expiry_time>? AND sent_expiry_notification=false",
            (twelve_hours_from_now, now),
        )
        expiring_users = cursor.fetchall()

        for user_id, user_first_name, username in expiring_users:
            cursor.execute(
                "UPDATE users SET sent_expiry_notification=true WHERE username=?",
                (username,),
            )
            conn.commit()

            result = cursor.execute(
                "SELECT expiry_time, tg_username FROM users WHERE username=?",
                (username,),
            ).fetchone()

            expiry_time = result[0]
            tg_username = result[1]

            remaining_time = datetime.fromtimestamp(expiry_time) - datetime.now()

            remaining_time_str = ""
            if remaining_time.days > 0:
                remaining_time_str += f"{remaining_time.days} days, "
            remaining_time_str += f"{remaining_time.seconds // 3600} hours, "
            remaining_time_str += f"{(remaining_time.seconds // 60) % 60} minutes"

            if tg_username:
                message = f"⏰ [{user_first_name}](tg://user?id={user_id}) Your plan for user `{username}` will expire in {remaining_time_str}."
            else:
                message = f"⏰ Plan for user `{username}` will expire in {remaining_time_str}."
            message += "\n\nPlease contact the admin if you want to extend the plan. 🔄"
            message += "\nYour data will be deleted after the expiry time. 🗑️"

            if user_id:
                # Send the message to that user_id in DM
                await client.send_message(user_id, message)
            else:
                await client.send_message(ADMIN_ID, message)

            # alert the admin that the user is expiring soon
            message = (
                f"⏰ Plan for user `{username}` will expire in {remaining_time_str}."
            )
            await client.send_message(ADMIN_ID, message)
        # Check expired users and notify admin to take necessary action
        cursor.execute(
            "SELECT tg_user_id, tg_username, username FROM users WHERE expiry_time<=? AND is_expired=false",
            (now,),
        )
        expired_users = cursor.fetchall()

        for tg_user_id, tg_username, username in expired_users:
            cursor.execute(
                "UPDATE users SET is_expired=true WHERE username=?", (username,)
            )
            conn.commit()

            message = f"❌ Your plan for the user: `{username}` has been expired."
            message += "\n\nThanks for using our service. 🙏"
            message += "\nFeel free to contact the admin for any queries. 📞"

            # Send the message to the user in DM
            await client.send_message(
                tg_user_id,
                message,
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


# --- Callback Query Handlers ---
@client.on(events.CallbackQuery(pattern=re.compile(r"cancel")))
async def handle_cancel(event):
    username = event.data.decode().split()[1]
    prev_msg = (
        f"⚠️ Plan for user `{username}` has expired. Please take necessary action."
    )
    cursor.execute("UPDATE users SET is_expired=true WHERE username=?", (username,))
    conn.commit()

    await event.edit(prev_msg + "\n\n" + "🚫 Action canceled.")


@client.on(events.CallbackQuery(pattern=re.compile(r"delete_user")))
async def handle_delete_user(event):
    username = event.data.decode().split()[1]
    await delete_system_user(username, event)


@client.on(events.CallbackQuery(pattern=re.compile(r"clean_db")))
async def handle_clean_db(event):
    username = event.data.decode().split()[1]
    cursor.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    await event.edit(f"✅ User `{username}` deleted from the database.")


# --- Main Execution ---
async def main():
    await client.start()
    await client.run_until_disconnected()


loop = asyncio.get_event_loop()
loop.create_task(notify_expiry())
loop.run_until_complete(main())
