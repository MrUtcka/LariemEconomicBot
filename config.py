import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
COMMAND_PREFIX = "/"

DB_NAME = "economy.db"

DEFAULT_BALANCE = 100
MIN_BET = 10

LOG_DIR = "logs"
