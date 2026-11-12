"""Constants of the HP Printer integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Final

DOMAIN: Final = "hp"
VERSION: Final = "1.0.0"
LOGGER: Final = logging.getLogger(__package__)

CONF_SCAN_INTERVAL: Final = "scan_interval"
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600

# Page counters and ink levels only change while the printer works: read every few minutes,
# and right after a job ends, instead of at every status poll.
USAGE_INTERVAL: Final = timedelta(minutes=5)
# Network adapters and cloud registration.
NETWORK_INTERVAL: Final = timedelta(minutes=30)
# Identity and firmware: at setup, when the printer comes back, and every few hours.
DEVICE_INTERVAL: Final = timedelta(hours=6)
# An endpoint the printer answered 404 to is asked again this often only.
UNSUPPORTED_RETRY: Final = timedelta(hours=6)

# A printer that is off answers nothing: give up quickly on the connection, more slowly on a
# slow embedded web server that did accept it.
CONNECT_TIMEOUT: Final = 4
REQUEST_TIMEOUT: Final = 15
# Embedded web servers are small: never more than this many requests at once per printer.
MAX_PARALLEL_REQUESTS: Final = 2
# A failed status request is tried again once after this delay before the printer counts as offline.
RETRY_DELAY: Final = 2.0

# The last data is saved this long after it changes, to survive restarts with the printer off.
SAVE_DELAY: Final = 30
STORAGE_VERSION: Final = 1

# Statuses of a printer at work: when the status leaves one of these, the counters are read again.
BUSY_STATUSES: Final = frozenset({"processing", "copying", "scan_processing", "cancel_job"})

# Status sensor values. The keys of the core integration are kept, so its automations keep working;
# "other" stands for a status this integration does not know (the raw one is in an attribute).
STATUSES: Final = (
    "ready",
    "processing",
    "copying",
    "scan_processing",
    "cancel_job",
    "in_power_save",
    "initializing",
    "shutting_down",
    "off",
    "tray_empty",
    "paper_jam",
    "close_door_or_cover",
    "other",
)
