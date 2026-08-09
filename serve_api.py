"""Explicit ASGI entrypoint; importing ``strata.api`` remains side-effect free."""

from strata.api import create_app


app = create_app()

