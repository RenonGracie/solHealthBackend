#!/usr/bin/env python
"""Application entry point."""
import os

from src import create_app
from src.config import get_config

if __name__ == "__main__":
    config = get_config(os.getenv("ENV", "dev"))
    app = create_app(config)

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=config.DEBUG)
