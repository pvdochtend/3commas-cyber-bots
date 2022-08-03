#!/usr/bin/env python3
"""Cyberjunky's 3Commas bot helpers."""
import argparse
import configparser
import asyncio
import os
import sys
import time
import json
import re
from pathlib import Path
from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import ChatAdminRequiredError

from helpers.logging import Logger, NotificationHandler


def load_config():
    """Create default or load existing config file."""

    cfg = configparser.ConfigParser()
    if cfg.read(f"{datadir}/{program}.ini"):
        return cfg

    cfg["settings"] = {
        "timezone": "Europe/Amsterdam",
        "debug": True,
        "logrotate": 7,
        "tgram-phone-number": "Your Telegram Phone number",
        "tgram-channel": "Telegram Channel name to watch",
        "tgram-api-id": "Your Telegram API ID",
        "tgram-api-hash": "Your Telegram API Hash",
        "notifications": False,
        "notify-urls": ["notify-url1"],
        "blacklist-msg": ["honeypot", "risk"],
        "blacklist-line": ["Owner"],
    }

    with open(f"{datadir}/{program}.ini", "w") as cfgfile:
        cfg.write(cfgfile)

    return None


# Start application
program = Path(__file__).stem

# Parse and interpret options.
parser = argparse.ArgumentParser(description="Cyberjunky's Tamer bot helper.")
parser.add_argument(
    "-d", "--datadir", help="directory to use for config and logs files", type=str
)

args = parser.parse_args()
if args.datadir:
    datadir = args.datadir
else:
    datadir = os.getcwd()

# Create or load configuration file
config = load_config()
if not config:
    # Initialise temp logging
    logger = Logger(datadir, program, None, 7, False, False)
    logger.info(
        f"Created example config file '{datadir}/{program}.ini', edit it and restart the program"
    )
    sys.exit(0)
else:
    # Handle timezone
    if hasattr(time, "tzset"):
        os.environ["TZ"] = config.get(
            "settings", "timezone", fallback="Europe/Amsterdam"
        )
        time.tzset()

    # Init notification handler
    notification = NotificationHandler(
        program,
        config.getboolean("settings", "notifications"),
        config.get("settings", "notify-urls"),
    )

    # Initialise logging
    logger = Logger(
        datadir,
        program,
        notification,
        int(config.get("settings", "logrotate", fallback=7)),
        config.getboolean("settings", "debug"),
        config.getboolean("settings", "notifications"),
    )

logger.info(f"Loaded configuration from '{datadir}/{program}.ini'")

# Configuration settings
monitor = config.get("settings", "tgram-channel")
blacklist_msg = config.get("settings", "blacklist-msg")
blacklist_line = config.get("settings", "blacklist-line")

# Setup the Telegram Client
client = TelegramClient(
    f"{datadir}/{program}",
    config.get("settings", "tgram-api-id"),
    config.get("settings", "tgram-api-hash"),
)
client.start(config.get("settings", "tgram-phone-number"))

async def setup():
    """Setup."""
    user = await client.get_me()
    logger.info("Started relaying as {}".format(user.first_name))
    await client.get_dialogs()

def blacklist(words, line, whole=False):
    """Check for string in line."""
    if whole:
        for ln in line:
            for word in json.loads(words.replace("'", '"')):
                if word in ln:
                    return word
    else:
        for word in json.loads(words.replace("'", '"')):
            if word in line:
                return word
    return None

@client.on(events.NewMessage(chats=monitor))
async def my_event_handler(event):
    """Parse messages."""
    contract = ""

    if event.message.message:
        lines = event.message.message.split("\n")
        found = blacklist(blacklist_msg, lines, True)
        if found:
            logger.info(f"Found blacklisted word '{found}' in telegram message, skipping.")
        else:    
            for line in lines:
                temp=re.findall(r'\b[0x]\w+', line)
                if len(temp):
                    found = blacklist(blacklist_line, line)
                    if found:
                        logger.info(f"Found blacklisted word '{found}' in contract line, skipping.")
                        continue

                    contract = temp[0]
                    logger.info(f"Found contract: '{contract}' in telegram message")

                    try:
                        logger.info(f"Sent contract command for '{contract}'")
                        await client.send_message(monitor, "/safe " + contract + "\n")
                    except ChatAdminRequiredError:
                        logger.error(
                            f"Not enough priviledge to write to telegram channel {monitor}"
                        )
                else:
                    logger.debug(f"Could not extract contract from {line}")
            else:
                logger.debug("No valid trigger message")
    else:
        logger.debug("No valid trigger message")


loop = asyncio.get_event_loop()
loop.run_until_complete(setup())
client.run_until_disconnected()
