import os

import dotenv

dotenv.load_dotenv()

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
