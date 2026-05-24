"""Bitbucket credential helper — builds authenticated git clone URLs.

Supports:
  - Bitbucket Cloud  (bitbucket.org)
  - Bitbucket Server / Data Center (self-hosted)

Credentials stored in OS keyring:
  keyring.get_password("oapw:bitbucket", username)  → app password / access token

Usage:
  oapw auth bitbucket --username myuser
  oapw kb sync --repo https://bitbucket.org/workspace/repo
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class BitbucketCred:
    username: str
    password: str  # Bitbucket App Password or access token
    is_cloud: bool


def save_credential(username: str, password: str) -> None:
    """Store a Bitbucket App Password in the OS keyring."""
    import keyring
    keyring.set_password("oapw:bitbucket", username, password)


def load_credential(username: str) -> str | None:
    """Load a Bitbucket App Password from the OS keyring."""
    try:
        import keyring
        return keyring.get_password("oapw:bitbucket", username)
    except Exception:
        return None


def build_auth_url(clone_url: str, username: str, password: str) -> str:
    """Inject credentials into an HTTPS clone URL.

    https://bitbucket.org/ws/repo.git
        → https://user:pass@bitbucket.org/ws/repo.git

    https://selfhosted.company.com/scm/proj/repo.git
        → https://user:pass@selfhosted.company.com/scm/proj/repo.git
    """
    import urllib.parse
    parsed = urllib.parse.urlparse(clone_url)
    # Encode special chars in username/password
    auth = f"{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}"
    authed = parsed._replace(netloc=f"{auth}@{parsed.hostname}"
                             + (f":{parsed.port}" if parsed.port else ""))
    return urllib.parse.urlunparse(authed)


def is_cloud(url: str) -> bool:
    return "bitbucket.org" in url


def repo_slug(url: str) -> str:
    """Extract a short name from a Bitbucket clone URL.

    https://bitbucket.org/workspace/my-repo.git → "my-repo"
    """
    m = re.search(r"/([^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else "repo"
