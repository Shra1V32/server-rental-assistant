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
from fpdf import FPDF
from tabulate import tabulate
from telethon import Button, TelegramClient, events
from weasyprint import HTML

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


# Table for active subscription users
create_table(
    "users",
    """
     user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE DEFAULT NULL,
    linux_username TEXT UNIQUE NOT NULL,
    linux_password TEXT NOT NULL,
    creation_time INTEGER DEFAULT (strftime('%s', 'now'))
    """,
)

create_table(
    "telegram_users",
    """
    tg_user_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    tg_username TEXT DEFAULT NULL,
    tg_first_name TEXT DEFAULT NULL,
    tg_last_name TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    """,
)

# Table for server rental plan details
create_table(
    "rentals",
    """
    rental_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    telegram_id INTEGER DEFAULT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    plan_duration INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL CHECK (currency IN ('INR', 'USD')), -- Enum-like check
    is_expired INTEGER DEFAULT 0 CHECK (is_expired IN (0, 1)), -- BOOLEAN stored as INTEGER
    is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
    sent_expiry_notification INTEGER DEFAULT 0 CHECK (sent_expiry_notification IN (0, 1)),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (telegram_id) REFERENCES telegram_users(tg_user_id) ON DELETE SET NULL
    """,
)

create_table(
    "payments",
    """
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL CHECK (currency IN ('INR', 'USD')),
    payment_date INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    """,
)

indexes = [
    "CREATE INDEX IF NOT EXISTS idx_users_uuid ON users(uuid);",
    "CREATE INDEX IF NOT EXISTS idx_users_linux_username ON users(linux_username);",
    "CREATE INDEX IF NOT EXISTS idx_telegram_users_user_id ON telegram_users(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_rentals_user_id ON rentals(user_id);"
]

for index in indexes:
    cursor.execute(index)

conn.commit()

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
    day = date.day
    return date.strftime(f"{day}{day_suffix} %B %Y, %I:%M %p IST")


async def get_exchange_rate(from_currency, to_currency):
    url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data["rates"][to_currency]


# --- System User Management ---
def create_system_user(username, password):
    return True
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


async def change_password(username):
    """
    Change the password of a system user
    """
    password = generate_password()
    hashed_password = subprocess.run(
        ["openssl", "passwd", "-6", password],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["sudo", "usermod", "-p", hashed_password, username],
        check=True,
    )
    return password


async def remove_ssh_auth_keys(username) -> tuple[bool, str]:
    """
    Remove the SSH authorized keys for a system user
    """
    try:
        subprocess.run(
            ["sudo", "rm", f"/home/{username}/.ssh/authorized_keys"], check=True
        )
    except subprocess.CalledProcessError:
        return (False, f"No authorized keys found for user {username}.")
    return (True, f"Authorized keys removed for user {username}.")


async def delete_system_user(username, event):
    await client.send_message(ADMIN_ID, f"🗑️ Deleting user `{username}`...")
    subprocess.run(["sudo", "pkill", "-9", "-u", username], check=False)
    try:
        subprocess.run(["sudo", "userdel", "-r", username], check=True)
    except subprocess.CalledProcessError as e:
        await event.edit(f"❌ Error deleting user `{username}`: {e}")
        return

    # Set the is_active to False for the user
    cursor.execute(
        """UPDATE rentals
        SET is_active = 0
        WHERE user_id = (
            SELECT user_id FROM users WHERE linux_username = ?
        )""",
        (username,),
    )
    conn.commit()
    await event.respond(f"✅ User `{username}` deleted.")


# --- Plan Management ---
async def modify_plan_duration(
    event, username, duration_change_seconds, action="reduced"
):
    cursor.execute("""SELECT end_time FROM rentals WHERE user_id = (
        SELECT user_id FROM users WHERE linux_username=?
        )""", (username,))
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
        """UPDATE rentals SET end_time=? WHERE user_id = (
            SELECT user_id FROM users WHERE linux_username=?)""",
        (new_expiry_time, username),
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
        UPDATE rentals
        SET sent_expiry_notification = 0, 
            is_expired = 0 
        WHERE user_id = (
            SELECT user_id FROM users WHERE linux_username = ?);
        """,
        (username,),
    )
    conn.commit()

    # Send notification to the user
    if send_notification:
        cursor.execute(
            """
            SELECT r.telegram_id, t.tg_first_name, r.end_time
            FROM rentals r
            LEFT JOIN telegram_users t ON r.telegram_id = t.tg_user_id
            WHERE r.user_id = (
                SELECT user_id FROM users WHERE linux_username = ?
            )
            """,
            (username,),
        )

        result = cursor.fetchone()
        if result:
            user_id, user_first_name, expiry_time = result
            remaining_time_str = parse_duration_to_human_readable(additional_seconds)
            expiry_date_str = get_date_str(expiry_time)
            message = (
                f"Dear {user_first_name},\n\n"
                f"🔥 Your plan has been extended by `{remaining_time_str}`.\n"
                f"📅 New expiry date: `{expiry_date_str}`"
                f"\n\n Enjoy your server! 🚀"
            )
            await client.send_message(user_id, message)


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
    VALUES ((SELECT user_id FROM users WHERE linux_username=?), ?, ?, ?)
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
        cursor.execute(
            """
            SELECT u.linux_username, r.is_expired
            FROM rentals r
            JOIN users u ON r.user_id = u.user_id
            """
        )
        usernames = cursor.fetchall()
        for row in usernames:
            if row[1]:
                continue
            await reduce_plan_helper(
                event, row[0], reduced_duration_seconds, send_notification=False
            )

        cursor.execute("""SELECT u.linux_username, r.end_time FROM rentals r 
                       JOIN users u ON r.user_id = u.user_id
                       """)
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
    cursor.execute(
        """
        SELECT u.linux_username, r.linux_password, r.end_time
        FROM rentals r
        JOIN users u ON r.user_id = u.user_id
        """
    )
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
    INSERT INTO users (uuid, linux_username, linux_password)
    VALUES (?, ?, ?)
    ON CONFLICT(linux_username) DO UPDATE SET uuid=excluded.uuid;
    """,
        (user_uuid, username, password),
    )

    cursor.execute(
        """
    INSERT INTO rentals (user_id, start_time, end_time, plan_duration, amount, currency)
    VALUES ((SELECT user_id FROM users WHERE linux_username=?), ?, ?, ?, ?, ?);
    """,
        (
            username,
            int(time.time()),
            expiry_time,
            plan_duration_seconds,
            amount_str,
            currency,
        ),
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
    - `/unlink_user <username>`: Clear the Telegram username and user id for a user.
    - `/list_users`: List all users along with their expiry dates and remaining time.
    - `/who`: List the currently connected users.
    - `/broadcast <message>`: Broadcast a message to all users.
    - `/link_user <username>`: Link a Telegram user to a system user.
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
    cursor.execute(
        "SELECT linux_username FROM users WHERE linux_username=?", (username,)
    )
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
        cursor.execute("""SELECT u.linux_username, r.is_active FROM rentals r 
                       JOIN users u ON r.user_id = u.user_id""")
        usernames = cursor.fetchall()
        for row in usernames:
            if not row[1]:
                continue
            await extend_plan_helper(
                event, row[0], additional_seconds, send_notification=False
            )

        cursor.execute("""SELECT u.linux_username, r.end_time FROM rentals r 
                       JOIN users u ON r.user_id = u.user_id""")
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
        WHERE user_id = (SELECT user_id FROM users WHERE linux_username = ?)
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


# Function to generate the PDF report
async def generate_report(event):
    rows = cursor.execute(
        """
        SELECT
            u.user_id,
            u.linux_username AS username,
            u.creation_time,
            r.end_time AS expiry_time,
            r.is_expired,
            COALESCE(SUM(p.amount), 0) AS total_payment,
            p.currency,
            COUNT(p.payment_id) AS payment_count
        FROM users u
        LEFT JOIN rentals r ON u.user_id = r.user_id
        LEFT JOIN payments p ON u.user_id = p.user_id
        GROUP BY u.user_id, u.linux_username, u.creation_time, r.end_time, r.is_expired, p.currency
        """
    ).fetchall()

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>User Payments Report</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
                background-color: #f4f4f4;
            }
            .container {
                width: 80%;
                margin: 0 auto;
                padding: 20px;
                background-color: #fff;
                box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
            }
            h1 {
                text-align: center;
                color: #333;
            }
            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }
            th, td {
                padding: 10px;
                border: 1px solid #ddd;
                text-align: left;
            }
            th {
                background-color: #4CAF50;
                color: white;
            }
            tr:nth-child(even) {
                background-color: #f2f2f2;
            }
            tr:nth-child(odd) {
                background-color: #e6f7ff;
            }
            tr:hover {
                background-color: #ddd;
            }
            .expired {
                color: red;
            }
            .active {
                color: green;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>User Payments Report</h1>
            <table>
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>Username</th>
                        <th>Creation Time (IST)</th>
                        <th>Expiry Time (IST)</th>
                        <th>Status</th>
                        <th>Total Payments</th>
                        <th>Total Earnings</th>
                    </tr>
                </thead>
                <tbody>
    """

    for row in rows:
        (
            user_id,
            username,
            creation_time,
            expiry_time,
            is_expired,
            total_payment,
            currency,
            payment_count,
        ) = row
        status = "Expired" if is_expired else "Active"

        # Convert timestamps to IST
        creation_ist = get_date_str(creation_time)
        expiry_ist = get_date_str(expiry_time)

        total_payment = total_payment if total_payment is not None else 0.00

        html_content += f"""
                    <tr>
                        <td>{user_id}</td>
                        <td>{username}</td>
                        <td>{creation_ist}</td>
                        <td>{expiry_ist}</td>
                        <td>{status}</td>
                        <td>{payment_count}</td>
                        <td>{total_payment:.2f} {currency if currency else ''}</td>
                    </tr>
        """

    html_content += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """

    # Generate PDF from HTML content
    pdf_file_path = "user_payments_report.pdf"
    HTML(string=html_content).write_pdf(pdf_file_path)

    # Send the generated PDF as a message
    await client.send_file(event.chat_id, pdf_file_path)


# /generate_report command
@client.on(events.NewMessage(pattern="/gen_report"))
@authorized_user
async def generate_report_command(event):
    await client.send_message(event.chat_id, "📄 Generating report...")
    await generate_report(event)


# /list_users command
@client.on(events.NewMessage(pattern="/list_users"))
@authorized_user
async def list_users(event):

    cursor.execute("""
        SELECT 
            u.linux_username AS username, 
            t.tg_user_id AS telegram_id, 
            t.tg_first_name, 
            r.end_time, 
            r.plan_duration, 
            r.is_expired, 
            r.is_active
        FROM rentals r
        LEFT JOIN users u ON r.user_id = u.user_id
        LEFT JOIN telegram_users t ON r.telegram_id = t.tg_user_id;"""
    )
    users = cursor.fetchall()

    if not users:
        await event.respond("🔍 No users found.")
        return

    # Get the number of active users
    active_users = [user for user in users if user[6]]

    response = f"👥 Total Users: {len(active_users)}\n\n"
    ist = pytz.timezone(TIME_ZONE)

    for (
        username,
        tg_user_id,
        tg_user_first_name,
        expiry_time,
        plan_duration_sec,
        is_expired,
        is_active,
    ) in users:
        expiry_date_ist = datetime.fromtimestamp(expiry_time, ist)
        expiry_date_str = get_date_str(expiry_time)

        if not is_active:
            # Active users means the user is not deleted from the system
            # Inactive users are the ones whose expiry date has passed
            # and they deleted from the system
            continue
        if not is_expired:
            remaining_time = expiry_date_ist - datetime.now(pytz.utc).astimezone(ist)
            remaining_time_str = ""
            if remaining_time.days > 0:
                remaining_time_str += f"{remaining_time.days} days, "
            remaining_time_str += f"{remaining_time.seconds // 3600} hours, "
            remaining_time_str += f"{(remaining_time.seconds // 60) % 60} minutes"

            tg_user_id = str(tg_user_id)

            if tg_user_id and tg_user_first_name:
                tg_tag = f"[{tg_user_first_name}](tg://user?id={tg_user_id})"
            else:
                tg_tag = tg_user_first_name if tg_user_first_name else "Not set"

            response += (
                f"✨ Username: `{username}`\n"
                f"   Telegram: {tg_tag}\n"
                f"   Plan: {parse_duration_to_human_readable(plan_duration_sec)}\n"
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

    # Prepend the message with the sender's name, along with the notice
    message = f"📢 **Broadcast Message**\n\n{message}"

    cursor.execute(
        "SELECT telegram_id FROM rentals WHERE (telegram_id IS NOT NULL) AND (is_active = 1)"
    )
    users = cursor.fetchall()

    for user_id in users:
        try:
            await client.send_message(user_id[0], message)
        except:
            pass

    await event.respond(f"✅ Broadcasted message to {len(users)} user(s).")


# /clear_user command
@client.on(events.NewMessage(pattern="/unlink_user"))
@authorized_user
async def clear_user(event):

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /unlink_user <username>")
        return

    username = event.message.text.split()[1]
    cursor.execute(
        """UPDATE telegram_users SET tg_username=NULL, tg_user_id=NULL, tg_first_name=NULL, tg_last_name=NULL WHERE user_id = (
            SELECT user_id FROM users WHERE linux_username = ? )""",
        (username,),
    )
    conn.commit()

    await event.respond(
        f"✅ Cleared Telegram username and user id for user `{username}`."
    )


# Link a Telegram user to a system user
# Create a button to link the user
# the user clicks the button and the bot sends the user's Telegram ID to the server
@client.on(events.NewMessage(pattern="/link_user"))
@authorized_user
async def link_user(event):

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /link_user <username>")
        return

    BOT_USERNAME = await client.get_me()

    username = event.message.text.split()[1]

    cursor.execute(
        """SELECT telegram_id FROM telegram_users WHERE user_id = (
            SELECT user_id FROM users WHERE linux_username = ?)""", (username,)
    )
    result = cursor.fetchone()

    if not result:
        await event.respond(f"❌ User `{username}` not found.")
        return

    user_id = result[0]
    if user_id:
        await event.respond(
            f"❌ User `{username}` is already linked to a Telegram user."
        )
        return

    # Get uuid for the user
    cursor.execute("SELECT uuid FROM users WHERE linux_username=?", (username,))
    result = cursor.fetchone()

    unique_id = result[0]

    if not unique_id:
        await event.respond(
            f"❌ User `{username}` doesn't have a valid UUID, randomizing..."
        )
        unique_id = str(uuid.uuid4())
        cursor.execute(
            "UPDATE users SET uuid=? WHERE linux_username=?", (unique_id, username)
        )
        conn.commit()

    await event.respond(
        f"🔗 Click the button below to link the Telegram user to the system user `{username}`.",
        buttons=[
            Button.url(
                "Link User", f"https://t.me/{BOT_USERNAME.username}?start={unique_id}"
            )
        ],
    )


# /who command
@client.on(events.NewMessage(pattern="/who"))
@authorized_user
async def list_connected_users(event):

    await send_connected_users(event)


# /run command (For running a shell command)
@client.on(events.NewMessage(pattern="/run"))
@authorized_user
async def run_command(event):

    if len(event.message.text.split()) < 2:
        await event.respond("❓ Usage: /run <command>")
        return

    command = event.message.text.split(" ", 1)[1]

    try:
        output = subprocess.run(
            command, shell=True, check=True, capture_output=True, text=True
        ).stdout
    except subprocess.CalledProcessError as e:
        output = e.stderr

    await event.respond(f"```\n{output}\n```")


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

    # Does the uuid exist in the database?
    cursor.execute("SELECT linux_username FROM users WHERE uuid=?", (user_uuid,))
    user = cursor.fetchone()
    if not user:
        await event.respond("❌ Invalid or expired link.")
        return
    username = user[0]
    print("Username:", username)


    password = cursor.execute(
        """SELECT u.linux_password
        FROM users u
        LEFT JOIN rentals r ON u.user_id = r.user_id
        WHERE u.linux_username = ?
        ORDER BY r.end_time DESC
        LIMIT 1;
""",
        (username,),
    )
    password = password.fetchone()[0]

    # Get the existing user_id for the user
    cursor.execute(
        "SELECT tg_user_id from telegram_users WHERE user_id = (SELECT user_id FROM users WHERE uuid=?)",
        (user_uuid,),
    )
    result = cursor.fetchone()
    fetched_user_id = result[0] if result else None

    tg_user_id = event.sender_id
    new_tg_username = event.sender.username
    user_first_name = event.sender.first_name
    user_last_name = event.sender.last_name

    if fetched_user_id is None:
        if new_tg_username is None:
            new_tg_username = tg_user_id

        cursor.execute(
            "INSERT OR IGNORE INTO telegram_users (tg_user_id, user_id, tg_username, tg_first_name, tg_last_name) VALUES (?, (SELECT user_id from users WHERE linux_username=?), ?, ?, ?)",
            (
                tg_user_id,
                username,
                new_tg_username,
                user_first_name,
                user_last_name,
            ),
        )
        conn.commit()

        # Update users table as well
        cursor.execute(
            """UPDATE rentals
            SET telegram_id = (
                SELECT tg_user_id
                FROM telegram_users
                WHERE user_id = (SELECT user_id FROM users WHERE linux_username = ?)
            )
            WHERE user_id = (SELECT user_id FROM users WHERE linux_username = ?);
            """,
            (username, username,),
        )
        conn.commit()

        # Tag the user for future refs
        msg = f"[{user_first_name}](tg://user?id={tg_user_id})\n\n"

        await event.respond(
            msg + f"🔑 **Username:** `{username}`\n🔒 **Password:** `{password}`"
        )
        await client.send_message(
            ADMIN_ID,
            f"🔑 Password sent to user [{user_first_name}](tg://user?id={tg_user_id}).",
        )
    else:
        # Tag the user for future refs
        msg = f"[{user_first_name}](tg://user?id={tg_user_id})\n\n"

        if fetched_user_id == tg_user_id:
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
        cursor.execute("""
            SELECT 
                t.tg_user_id AS telegram_id, 
                t.tg_first_name, 
                u.linux_username, 
                r.user_id
            FROM rentals r
            LEFT JOIN telegram_users t ON r.telegram_id = t.tg_user_id
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.end_time <= ? 
              AND r.end_time > ? 
              AND r.sent_expiry_notification = 0;""",
            (twelve_hours_from_now, now),
        )
        expiring_users = cursor.fetchall()

        for user_id, user_first_name, username in expiring_users:
            cursor.execute(
                """UPDATE rentals SET sent_expiry_notification=1
                WHERE user_id = (SELECT user_id FROM users WHERE linux_username=?)""",
                (username,),
            )
            conn.commit()

            result = cursor.execute(
                """SELECT end_time, telegram_id FROM rentals
                WHERE user_id = (SELECT user_id FROM users WHERE linux_username=?)""",
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
        cursor.execute( """
            SELECT 
                t.tg_user_id, 
                u.linux_username
            FROM rentals r
            LEFT JOIN telegram_users t ON r.telegram_id = t.tg_user_id
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.end_time <= ? 
              AND r.is_expired = 0;""",
            (now,),
        )
        expired_users = cursor.fetchall()

        for tg_user_id, username in expired_users:
            cursor.execute(
                """UPDATE rentals SET is_expired=1 
                WHERE user_id = (SELECT user_id FROM users WHERE linux_username=?)""", (username,)
            )
            conn.commit()

            message = f"❌ Your plan for the user: `{username}` has been expired."
            message += "\n\nThanks for using our service. 🙏"
            message += "\nFeel free to contact the admin for any queries. 📞"

            new_password = await change_password(username)

            # Remove the authorized ssh keys
            status, removal_str = await remove_ssh_auth_keys(username)

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
            await client.send_message(
                ADMIN_ID,
                f"🔑 New password for user `{username}`: `{new_password}`",
            )
            await client.send_message(ADMIN_ID, f"🔑 {removal_str}")

        await asyncio.sleep(60)  # Check every minute


# --- Callback Query Handlers ---
@client.on(events.CallbackQuery(pattern=re.compile(r"cancel")))
async def handle_cancel(event):
    username = event.data.decode().split()[1]
    prev_msg = (
        f"⚠️ Plan for user `{username}` has expired. Please take necessary action."
    )
    cursor.execute(
        """UPDATE rentals SET is_expired=1
        WHERE (user_id = (SELECT user_id FROM users WHERE linux_username = ?) AND is_expired=0)""",
        (username,),
    )
    conn.commit()

    await event.edit(prev_msg + "\n\n" + "🚫 Action canceled.")


@client.on(events.CallbackQuery(pattern=re.compile(r"delete_user")))
async def handle_delete_user(event):
    username = event.data.decode().split()[1]
    await delete_system_user(username, event)


@client.on(events.CallbackQuery(pattern=re.compile(r"clean_db")))
async def handle_clean_db(event):
    username = event.data.decode().split()[1]
    # cursor.execute("DELETE FROM users WHERE username=?", (username,))
    cursor.execute(
        """UPDATE rentals SET is_active=1
        WHERE user_id = (SELECT user_id FROM users WHERE linux_username = ?)""", (username,)
    )
    conn.commit()
    cursor.execute("""SELECT is_expired FROM rentals 
                   WHERE user_id = (SELECT user_id FROM users WHERE linux_username=?)""", (username,))
    is_expired = cursor.fetchone()[0]
    status = "Expired" if is_expired else "Active"
    await event.edit(
        f"✅ User `{username}` plan updated in the database. Status: `{status}`."
    )


@client.on(events.CallbackQuery(pattern=re.compile(r"tglink")))
async def handle_tglink(event):
    username = event.data.decode().split()[1]

    # Get the user_id from the event
    user_id = event.sender_id
    user_first_name = event.sender.first_name
    user_last_name = event.sender.last_name
    tg_username = event.sender.username

    # Update the user's Telegram ID in the database
    cursor.execute(
        """UPDATE telegram_users SET tg_user_id=?, tg_first_name=?, tg_last_name=? 
        WHERE user_id = (SELECT user_id FROM users WHERE linux_username=?""",
        (user_id, user_first_name, user_last_name, username),
    )

    conn.commit()

    # Tag the user for future refs
    msg = f"[{user_first_name}](tg://user?id={user_id})\n\n"
    await event.edit(
        msg + f"✅ User `{username}` linked to Telegram user `{tg_username}`."
    )


# --- Main Execution ---
async def main():
    await client.start()
    await client.run_until_disconnected()


loop = asyncio.get_event_loop()
loop.create_task(notify_expiry())
loop.run_until_complete(main())
