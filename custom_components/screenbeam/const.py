"""Constants for the ScreenBeam MoCA integration."""

from typing import Final

DOMAIN: Final = "screenbeam"
MANUFACTURER: Final = "ScreenBeam"

DEFAULT_USERNAME: Final = "admin"
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds; one poll is ~11 small requests
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

CONF_MODEL: Final = "model"
# The adapters do not report their model; these are offered in the options.
KNOWN_MODELS: Final = ["ECB6200", "ECB6250", "ECB7250"]
