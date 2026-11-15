"""Constants for the ScreenBeam MoCA integration."""

from typing import Final

DOMAIN: Final = "screenbeam"
MANUFACTURER: Final = "ScreenBeam"

DEFAULT_USERNAME: Final = "admin"
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds; one poll is ~11 small requests
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600
