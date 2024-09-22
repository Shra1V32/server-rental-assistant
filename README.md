# Server Plan Bot

Server Plan Bot is a Telegram bot designed to manage user accounts on a server. It allows administrators to create, delete, and extend user plans, as well as notify users of their plan expiry. The bot uses SQLite for database management and integrates with system commands to manage user accounts.

## Features

- **Create User**: Create a new user with a specified plan duration.
- **Delete User**: Delete an existing user.
- **Secure Password**: Generate a secure, memorable password for each user.
- **Admin Commands**: Ensures only admin is accessing the commands.
- **Extend Plan**: Extend the plan duration for a user.
- **Reduce Plan**: Reduce the plan duration for a user.
- **List Users**: List all users along with their plan expiry dates.
- **Notify Expiry**: Periodically notify users of their plan expiry.
- **Interactive User deletion**: Confirm user deletion before executing the command.

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
- useradd
- userdel
- sudo

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
    - **Create User**: `/create_user <username> <plan_duration>`
        - Example: `/create_user john 7d`
    - **Delete User**: `/delete_user <username>`
        - Example: `/delete_user john`
    - **Extend Plan**: `/extend_plan <username> <additional_duration>`
        - Example: `/extend_plan john 5d`
    - **Reduce Plan**: `/reduce_plan <username> <reduced_duration>`
        - Example: `/reduce_plan john 5d`
    - **List Users**: `/list_users`

## Code Overview

- **main.py**: The main script that contains the bot logic and command handlers.
- **constants.py**: Constants used in the bot.
- **.env**: Environment variables for the bot.
- **.gitignore**: Specifies files and directories to be ignored by Git.

### Key Functions and Handlers

- `create_user(event)`: Handles the `/create_user` command.
- `delete_user(event)`: Handles the `/delete_user` command.
- `extend_plan(event)`: Handles the `/extend_plan` command.
- `list_users(event)`: Handles the `/list_users` command.
- `notify_expiry()`: Periodically checks for expired plans and notifies users.

### Helper Functions

- `generate_password()`: Generates a secure, memorable password.
- `create_system_user(username, password)`: Creates a system user with the specified username and password.
- `parse_duration(duration_str)`: Parses a duration string (e.g., `7d`, `5h`) into seconds.

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request.

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Contact

For any questions or suggestions, please open an issue or contact the repository owner.