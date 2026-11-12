"""The web page for parents. Needs the optional web dependencies: pip install -e ".[web]"."""

from mm.web.app import create_app

__all__ = ["create_app"]
