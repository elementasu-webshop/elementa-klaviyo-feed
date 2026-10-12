"""Entry point selecting independently configured feed services.

FEED_MODE=ananas is set only for the Ananas Render service.
The existing Klaviyo Render service continues to use its original handler.
"""
import os

if os.environ.get("FEED_MODE", "klaviyo").lower() == "ananas":
    from ananas_app import app
else:
    from klaviyo_app import app
