"""Smartschool session with a resilient `authenticated_user` lookup."""
from __future__ import annotations

import json
import logging
import re

from smartschool import Smartschool

_LOGGER = logging.getLogger(__name__)

_AUTH_USER_RE = re.compile(r'"authenticatedUser"\s*:\s*')
_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _parse_authenticated_user(page_text: str) -> dict | None:
    """Extract the `authenticatedUser` object from a Smartschool page.

    Smartschool embeds it in a JS string as `\\u0022`-escaped JSON. The smartschool
    library's own parser (`parse_smsc_vars`) no longer matches that page layout, so
    after a fresh login (empty ~/.cache, e.g. after a Home Assistant core update
    recreated the container) `authenticated_user` stayed None and every call that needs
    it (messages, student profile, calendar) failed with "Could not retrieve
    authenticated user information".
    """
    text = _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), page_text)
    match = _AUTH_USER_RE.search(text)
    if not match:
        return None
    try:
        user = json.JSONDecoder().raw_decode(text, match.end())[0]
    except json.JSONDecodeError:
        return None
    return user if isinstance(user, dict) and user.get("id") else None


class HASmartschool(Smartschool):
    """Smartschool session that falls back to scraping the user from the home page."""

    @property
    def authenticated_user(self) -> dict | None:
        if self._authenticated_user is None:
            try:
                return Smartschool.authenticated_user.fget(self)
            except ValueError:
                pass
            # The session is logged in by now (the library's lazy login ran); read the user
            # from the home page ourselves.
            user = _parse_authenticated_user(self.get(self.create_url("/")).text)
            if user is None:
                raise ValueError("Could not retrieve authenticated user information")
            _LOGGER.debug("Smartschool authenticated user resolved via home page fallback")
            self.authenticated_user = user
        return self._authenticated_user

    @authenticated_user.setter
    def authenticated_user(self, new_user: dict | None) -> None:
        Smartschool.authenticated_user.fset(self, new_user)
