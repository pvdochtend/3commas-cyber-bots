#!/usr/bin/env python3
"""Cyberjunky's 3Commas bot helpers."""
import argparse
import configparser
import json
import os
import sys
import time
from pathlib import Path

from telethon import TelegramClient, events

from helpers.logging import Logger, NotificationHandler
from helpers.misc import format_pair
from helpers.threecommas import (
    close_threecommas_deal,
    get_threecommas_account_marketcode,
    init_threecommas_api,
    load_blacklist,
    trigger_threecommas_bot_deal,
)


def load_config():
    """Create default or load existing config file."""

    cfg = configparser.ConfigParser()
    if cfg.read(f"{datadir}/{program}.ini"):
        return cfg

    cfg["settings"] = {
        "timezone": "Europe/Amsterdam",
        "debug": False,
        "logrotate": 7,
        "3c-apikey": "Your 3Commas API Key",
        "3c-apisecret": "Your 3Commas API Secret",
        "tgram-phone-number": "Your Telegram Phone number",
        "tgram-api-id": "Your Telegram API ID",
        "tgram-api-hash": "Your Telegram API Hash",
        "notifications": False,
        "notify-urls": ["notify-url1"],
        "exchange": "Bittrex / Binance / Kucoin",
        "mode": "Telegram"
    }

    cfg["hodloo_5"] = {
        "bnb-botids": [12345, 67890],
        "btc-botids": [12345, 67890],
        "busd-botids": [12345, 67890],
        "eth-botids": [12345, 67890],
        "eur-botids": [12345, 67890],
        "usdt-botids": [12345, 67890],
    }

    cfg["hodloo_10"] = {
        "bnb-botids": [12345, 67890],
        "btc-botids": [12345, 67890],
        "busd-botids": [12345, 67890],
        "eth-botids": [12345, 67890],
        "eur-botids": [12345, 67890],
        "usdt-botids": [12345, 67890],
    }

    with open(f"{datadir}/{program}.ini", "w") as cfgfile:
        cfg.write(cfgfile)

    return None


async def handle_event(category, event):
    """Handle the received Telegram event"""

    logger.debug(
        "Received telegram message on %s: '%s'"
        % (category, event.message.text.replace("\n", " - "))
    )

    # Parse the event and do some error checking
    trigger = event.raw_text.splitlines()

    pair = trigger[0].replace("\n", "").replace("**", "")
    base = pair.split("/")[1]
    coin = pair.split("/")[0]

    logger.info(
        f"Received message on {category}% for {base}_{coin}"
    )

    if base.lower() not in ("bnb", "btc", "busd", "eth", "eur", "usdt"):
        logger.debug(
            f"{base}_{coin}: base '{base}' is not yet supported."
        )
        return

    botids = get_botids(category, base)

    if len(botids) == 0:
        logger.debug(
            f"{base}_{coin}: no valid botids configured for base '{base}'."
        )
        return

    await client.loop.run_in_executor(
        None, process_botlist, botids, coin
    )

    notification.send_notification()


def process_botlist(botidlist, coin):
    """Process the list of bots for the given coin"""

    for botid in botidlist:
        if botid:
            error, data = api.request(
                entity="bots",
                action="show",
                action_id=str(botid),
            )

            if data:
                # Check number of deals, otherwise error will occur anyway (save some processing)
                if data["active_deals_count"] >= data["max_active_deals"]:
                    logger.info(
                        f"Bot '{data['name']}' reached maximum number of "
                        f"deals ({data['max_active_deals']}). "
                        f"Cannot start a new deal for {coin}!",
                        True
                    )
                else:
                    process_bot_deal(data, coin, "LONG")
            else:
                if error and "msg" in error:
                    logger.error(
                        "Error occurred fetching bot (%s) data: %s" % (str(botid), error["msg"])
                    )
                else:
                    logger.error(
                        "Error occurred fetching bot (%s) data" % str(botid)
                    )


def process_bot_deal(thebot, coin, trade):
    """Check pair and trigger the bot deal."""

    # Gather some bot values
    base = thebot["pairs"][0].split("_")[0]
    bot_exchange = thebot["account_name"]
    minvolume = thebot["min_volume_btc_24h"]

    logger.debug("Base coin for this bot: %s" % base)
    logger.debug("Minimal 24h volume of %s BTC" % minvolume)

    # Get marketcode from array
    marketcode = marketcodes.get(thebot["id"])
    if not marketcode:
        return
    logger.info("Bot: %s" % thebot["name"])
    logger.info("Exchange %s (%s) used" % (bot_exchange, marketcode))

    # Construct pair based on bot settings and marketcode (BTC stays BTC, but USDT can become BUSD)
    pair = format_pair(logger, marketcode, base, coin)

    if trade == "LONG":
        # Check if pair is on 3Commas blacklist
        if pair in blacklist:
            logger.debug(
                f"Pair '{pair}' is on your 3Commas blacklist and was skipped",
                True
            )
            return

        # Check if pair is in bot's pairlist
        if pair not in thebot["pairs"]:
            logger.info(
                f"Pair '{pair}' is not in '{thebot['name']}' pairlist and was skipped",
                True
            )
            return

        # We have valid pair for our bot so we trigger an open asap action
        logger.info("Triggering your 3Commas bot for a start deal of '%s'" % pair)
        trigger_threecommas_bot_deal(logger, api, thebot, pair, (len(blacklistfile) > 0))
    else:
        # Find active deal(s) for this bot so we can close deal(s) for pair
        deals = thebot["active_deals"]
        if deals:
            for deal in deals:
                if deal["pair"] == pair:
                    logger.info("Triggering your 3Commas bot for a (panic) sell of '%s'" % pair)
                    close_threecommas_deal(logger, api, deal["id"], pair)
                    return

            logger.info(
                "No deal(s) running for bot '%s' and pair '%s'"
                % (thebot["name"], pair), True
            )
        else:
            logger.info("No deal(s) running for bot '%s'" % thebot["name"], True)


def prefetch_marketcodes():
    """Gather and store marketcodes for all bots."""

    marketcodearray = {}
    botids = list()

    for category in ("5", "10"):
        for base in ("bnb", "btc", "busd", "eth", "eur", "usdt"):
            botids += get_botids(category, base)

    logger.debug(
        f"Botids collected: {botids}"
    )

    for botid in botids:
        if botid:
            boterror, botdata = api.request(
                entity="bots",
                action="show",
                action_id=str(botid),
            )
            if botdata:
                accountid = botdata["account_id"]
                # Get marketcode (exchange) from account if not already fetched
                marketcode = get_threecommas_account_marketcode(logger, api, accountid)
                marketcodearray[botdata["id"]] = marketcode
            else:
                if boterror and "msg" in boterror:
                    logger.error(
                        "Error occurred fetching marketcode data: %s" % boterror["msg"]
                    )
                else:
                    logger.error("Error occurred fetching marketcode data")

    return marketcodearray


def get_botids(category, base):
    """Get list of botids from configuration based on category and base"""

    return json.loads(config.get(f"hodloo_{category}", f"{base.lower()}-botids"))


# Start application
program = Path(__file__).stem

# Parse and interpret options.
parser = argparse.ArgumentParser(description="Cyberjunky's 3Commas bot helper.")
parser.add_argument("-d", "--datadir", help="data directory to use", type=str)
parser.add_argument("-b", "--blacklist", help="blacklist to use", type=str)

args = parser.parse_args()
if args.datadir:
    datadir = args.datadir
else:
    datadir = os.getcwd()

# pylint: disable-msg=C0103
if args.blacklist:
    blacklistfile = f"{datadir}/{args.blacklist}"
else:
    blacklistfile = ""

# Create or load configuration file
config = load_config()
if not config:
    logger = Logger(datadir, program, None, 7, False, False)
    logger.info(
        f"Created example config file '{program}.ini', edit it and restart the program"
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

# Which Exchange to use?
exchange = config.get("settings", "exchange")
if exchange not in ("Bittrex", "Binance", "Kucoin"):
    logger.error(
        f"Exchange {exchange} not supported. Must be 'Bittrex', 'Binance' or 'Kucoin'!"
    )
    sys.exit(0)

# Which Mode to use?
mode = config.get("settings", "mode")
if mode not in ("Telegram", "Websocket"):
    logger.error(
        f"Mode {mode} not supported. Must be 'Telegram' or 'Websocket'!"
    )
    sys.exit(0)

# Initialize 3Commas API
api = init_threecommas_api(config)

# Prefect marketcodes for all bots
marketcodes = prefetch_marketcodes()

# Prefect blacklists
blacklist = load_blacklist(logger, api, blacklistfile)

if mode == "Telegram":
    # Watchlist telegram trigger
    client = TelegramClient(
        f"{datadir}/{program}",
        config.get("settings", "tgram-api-id"),
        config.get("settings", "tgram-api-hash"),
    ).start(config.get("settings", "tgram-phone-number"))

    @client.on(events.NewMessage(chats=f"Hodloo {exchange} 5%"))
    async def callback_5(event):
        """Receive Telegram message."""

        await handle_event("5", event)

        notification.send_notification()

    @client.on(events.NewMessage(chats=f"Hodloo {exchange} 10%"))
    async def callback_10(event):
        """Receive Telegram message."""

        await handle_event("10", event)

        notification.send_notification()

    # Start telegram client
    client.start()
    logger.info(
        f"Listening to telegram chat 'Hodloo {exchange} 5%' and "
        f"'Hodloo {exchange} 10%' for triggers",
        True,
    )
    client.run_until_disconnected()
# No else case, mode is already checked before this statement
