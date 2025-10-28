import logging

from flask import Flask


def setup_logging(app: Flask) -> None:
    """Configure basic logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    )
    # Ensure Flask's internal logger uses the same level
    app.logger.setLevel(logging.INFO)
