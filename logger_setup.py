"""
logger_setup.py — Centralized logging configuration for the Invoice Manager.
"""

import logging
import sys

# Silence noisy third-party loggers
NOISY_LOGGERS = [
    "fontTools", "fontTools.subset", "fontTools.ttLib",
    "playwright", "httpx",
    "googleapiclient", "google_auth_httplib2",
    "PIL", "urllib3", "google_genai", "google.auth",
    "charset_normalizer", "absl", "streamlit", "asyncio"
]

def setup_logging(level=logging.INFO):
    """
    Configures the root logger with a consistent format across all modules.
    Format: timestamp | module:line | level | message
    """
    # Create a handler if not already present (avoid duplicates)
    if not logging.getLogger().handlers:
        handler = logging.StreamHandler(sys.stdout)
        # The line number is included via %(lineno)d
        formatter = logging.Formatter(
            "%(asctime)s | %(name)s:%(lineno)d | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(level)

    # Apply silencers aggressively
    for logger_name in NOISY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.ERROR)
    
    for internal in ["drive_service", "gmail_service", "gmail_scanner", "email_processor", "gemini_service", "file_processor"]:
        logging.getLogger(internal).setLevel(level)

    # Force absolute silence for these specific noisy ones
    for noisy in ["asyncio", "playwright"]:
        l = logging.getLogger(noisy)
        l.setLevel(logging.ERROR)
        l.propagate = False # Prevent bubbling up to the root logger

# Auto-run when imported
setup_logging()
