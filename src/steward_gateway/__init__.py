"""Steward's gateway (spec 3): the only process that calls Anthropic."""
import os

# P2: without this, Hugging Face's library adds the Python, torch and library versions to the user agent of its model
# downloads. It reads the setting once, when it is first imported, and every gateway command imports this package
# first, so it holds for the images, the guide's systemd unit and any other install alike.
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
