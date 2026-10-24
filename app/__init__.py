__version__ = "3.1.1"

# Where "Check for updates" looks for new Windows releases (GitHub Releases of this repository).
# This needs the repository to be public. For a private repository, put the latest.json file that
# each GitHub build attaches to its release on any public web address and set UPDATE_JSON_URL to it,
# e.g. "https://www.example.com/imageresizeshare/latest.json".
UPDATE_REPO = "ifixdigitaluk-design/ImageResizeShare"
UPDATE_JSON_URL = ""

# Who receives error reports (Help › Send an error report). Leave empty to let the user save or
# copy the report file and send it themselves. Example: "support@example.com", "447700900123".
SUPPORT_EMAIL = ""
SUPPORT_WHATSAPP = ""


def build_number() -> int:
    """The GitHub build number of this copy (0 when run from source or built on a PC)."""
    try:
        from app._build import BUILD
        return int(BUILD)
    except Exception:
        return 0
