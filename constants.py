import os

import dotenv

dotenv.load_dotenv()

TIME_ZONE = "Asia/Kolkata"
BE_NOTED_TEXT = """ 
"""  # Add your notes text to show on /create_user command
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
