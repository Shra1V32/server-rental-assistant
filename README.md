# Server Plan Bot

Server Plan Bot is a Telegram bot designed to manage user accounts on a server. It allows administrators to create, delete, and extend user plans, as well as notify users of their plan expiry. The bot uses SQLite for database management and integrates with system commands to manage user accounts.

## Features

- **Create User**: Create a new user with a specified plan duration and amount. It also generates a secure password.
- **Delete User**: Delete an existing user from both the system and the database. 
- **Extend Plan**: Extend the plan duration for a user, optionally with an additional payment.
- **Reduce Plan**: Reduce the plan duration for a user.
- **List Users**: List all users along with their plan expiry dates, remaining time, and Telegram details.
- **Notify Expiry**: Periodically notify users of their plan expiry via Telegram.
- **Secure Password**: Generate a secure, memorable password for each user, accessible through a unique link.
- **Admin Commands**: Ensures only the specified admin user can access management commands.
- **Payment Tracking**: Records payments made by users, including amount, currency, and date.
- **Earnings Summary**: Calculates and displays the total earnings from user payments.
- **User Linking**: Allows linking of Telegram users to system accounts for password retrieval and notifications.
- **Interactive User Deletion**: Provides options to cancel or confirm user deletion after plan expiry.
- **Database Synchronization**: Synchronizes the user database with the system to ensure consistency.
- **Debit/Credit**: Allows the admin to manually debit or credit amounts to user accounts.
- **Payment History**: Displays the payment history for a specific user.
- **Broadcast**: Sends a message to all registered Telegram users.
- **Clear User**: Removes the Telegram username and user ID association from a user account.
- **Connected Users**: Displays a list of currently connected users on the server.
- **Automated Actions**:
    - Notifies users about upcoming expiry (within 12 hours).
    - Marks users as expired when their plan expires.
    - Sends expiry notifications to users and prompts admin for action (delete or cancel).

# To Do
- Automated action to add the server subscribers to the private telegram group.
- Automated action to kick the user from the group when the plan expires.
- Automated group link revoke when the user joins/leaves.
- `subscribe` for the slots of the server, so that the user can get notified when the slot is available.
- `unsubscribe` to stop the notifications.
- `faq` to get the frequently asked questions.

## Prerequisites

- Python 3.7+
- Telegram account and bot token
- SQLite
- [`openssl`](https://www.openssl.org/)
- `useradd`
- `userdel`
- `sudo`
- `w` (for listing connected users)
- `aiohttp`
- `pytz`
- `telethon`

## Installation

1. **Clone the repository**:
    ```sh
    git clone https://github.com/Shra1V32/server-rental-assistant.git
    cd server-rental-assistant
    ```

2. **Install the required packages**:
    ```sh
    pip install -r requirements.txt
    ```

3. **Set up environment variables**:
    Create a `.env` file in the root directory with the following content:
    ```env
    API_ID = your_api_id # Your Telegram API ID, can be found in my.telegram.org
    API_HASH = "your_api_hash" # Your Telegram API hash, can be found in my.telegram.org
    BOT_TOKEN = "your_bot_token" # Your Telegram bot token
    ADMIN_ID = your_admin_id # Your Telegram user ID, ask Rose bot with /id
    SSH_HOSTNAME = "your_ssh_host" # Your SSH hostname
    SSH_PORT = your_ssh_port # Your SSH port
    GROUP_ID = your_group_id # The group id where the bot is to be added
    TIME_ZONE = "Asia/Kolkata" # Your desired time zone (e.g., "America/New_York")
    BE_NOTED_TEXT = "This is a sample note for users." # Optional: Text to be included in user creation message
    ```
    Replace the placeholders with your actual values.
    > Note: API_ID, ADMIN_ID, SSH_HOSTNAME, SSH_PORT, and GROUP_ID should be integers.

4. **Initialize the SQLite database**:
    The database will be automatically created and initialized when you run the bot for the first time.

## Usage

1. **Run the bot**:
    ```sh
    python main.py
    ```

2. **Telegram Commands**:

   **Admin Commands:**
    - **Create User**: `/create_user <username> <plan_duration> <amount> <currency (INR/USD)>`
        - Example: `/create_user john 7d 500 INR`
    - **Delete User**: `/delete_user <username>`
        - Example: `/delete_user john`
    - **Extend Plan**: `/extend_plan <username> <additional_duration> [amount] [currency]`
        - Example: `/extend_plan john 5d 300 INR`
    - **Reduce Plan**: `/reduce_plan <username> <reduced_duration>`
        - Example: `/reduce_plan john 5d`
    - **Sync Database**: `/sync_db`
    - **Debit Amount**: `/debit <username> <amount> <currency>`
        - Example: `/debit john 100 INR`
    - **Credit Amount**: `/credit <username> <amount> <currency>`
        - Example: `/credit john 100 INR`
    - **Earnings**: `/earnings`
    - **Payment History**: `/payment_history <username>`
        - Example: `/payment_history john`
    - **Clear User**: `/clear_user <username>`
        - Example: `/clear_user john`
    - **List Users**: `/list_users`
    - **Broadcast**: `/broadcast <message>`
        - Example: `/broadcast Maintenance scheduled for tomorrow at 2:00 AM IST.`
    - **Link User**: `/link_user <username>`
        - Example: `/link_user john`
    - **Connected Users**: `/who`
    - **Help**: `/help`

   **User Commands:**
    - **Start**: `/start <unique_link>` (sent to the user upon account creation)


## Code Overview

- **main.py**: The main script that contains the bot logic and command handlers.
- **constants.py**: Constants used in the bot (API keys, admin ID, etc.).
- **.env**: Environment variables for the bot.
- **.gitignore**: Specifies files and directories to be ignored by Git.
- **server_plan.db**: SQLite database file (created automatically).

### Key Functions and Handlers

- `create_user(event)`: Handles the `/create_user` command.
- `delete_user_command(event)`: Handles the `/delete_user` command.
- `extend_plan(event)`: Handles the `/extend_plan` command.
- `reduce_plan(event)`: Handles the `/reduce_plan` command.
- `list_users(event)`: Handles the `/list_users` command.
- `notify_expiry()`: Periodically checks for expired plans and notifies users.
- `start_command(event)`: Handles the `/start` command and password retrieval.

### Helper Functions

- `generate_password()`: Generates a secure, memorable password.
- `create_system_user(username, password)`: Creates a system user with the specified username and password.
- `parse_duration(duration_str)`: Parses a duration string (e.g., `7d`, `5h`) into seconds.
- `get_date_str(epoch)`: Converts a Unix timestamp to a human-readable date string.
- `get_exchange_rate(from_currency, to_currency)`: Fetches the current exchange rate from an API.
- `process_payment(event, username, amount_str, currency)`: Records a payment in the database.
- `is_authorized_user(user_id)`: Checks if a user is authorized to use admin commands.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Contact

For any questions or suggestions, please open an issue or contact the repository owner.
Use code with caution.