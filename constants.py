import os

import dotenv


# Check if the environment variables are set and not empty. If not, raise an exception.
def check_env():
    if (
        not os.getenv("API_ID")
        or not os.getenv("API_HASH")
        or not os.getenv("BOT_TOKEN")
        or not os.getenv("ADMIN_ID")
    ):
        raise Exception(
            "Bot Environment variables are not set. Please set them in .env file."
        )
    if not os.getenv("SSH_PORT") or not os.getenv("SSH_HOSTNAME"):
        raise Exception(
            "SSH Environment variables are not set. Please set them in .env file."
        )

    if not os.getenv("GROUP_ID"):
        # Raise warning if GROUP_ID is not set
        print("Warning: GROUP_ID is not set in .env file. Continuing without it.")


dotenv.load_dotenv()

check_env()

TIME_ZONE = "Asia/Kolkata"

# Take data from the notes.txt file
try:
    BE_NOTED_TEXT = open("notes.txt", "r").read()
except FileNotFoundError:
    BE_NOTED_TEXT = ""
SSH_PORT = os.getenv("SSH_PORT")
SSH_HOSTNAME = os.getenv("SSH_HOSTNAME")

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

ADJECTIVES = [
    "crazy",
    "sunny",
    "happy",
    "wild",
    "quick",
    "witty",
    "jolly",
    "zany",
    "lazy",
    "sleepy",
    "dopey",
    "grumpy",
    "bashful",
    "sneezy",
    "curly",
]
NOUNS = [
    "cat",
    "evening",
    "river",
    "breeze",
    "mountain",
    "ocean",
    "sun",
    "moon",
    "tree",
    "flower",
    "star",
    "space",
    "forest",
    "meadow",
    "rain",
    "snow",
    "wind",
]
