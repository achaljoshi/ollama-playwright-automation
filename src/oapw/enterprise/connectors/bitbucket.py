"""Bitbucket credential helper — builds authenticated git clone URLs.

Supports:
  - Bitbucket Cloud  (bitbucket.org) with API tokens (preferred) or App Passwords (legacy)
  - Bitbucket Server / Data Center (self-hosted) with username + token/password

Bitbucket Cloud API tokens (replacing App Passwords from July 2026):
  Create at: Bitbucket → Personal Settings → API tokens → Create token
  Scope required: Repositories: Read
  Authentication format: x-token-auth:{token}  (username is ignored for clone URLs)

Credentials stored in OS keyring:
  keyring.get_password("oapw:bitbucket", username)  → API token or App Password

Usage:
  oapw auth bitbucket --username ajoshi
  oapw kb sync --repo https://bitbucket.org/workspace/repo --username ajoshi
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class BitbucketCred:
    username: str
    token: str       # Bitbucket API token (preferred) or legacy App Password
    is_cloud: bool


def save_credential(username: str, token: str) -> None:
    """Store a Bitbucket API token (or legacy App Password) in the OS keyring."""
    import keyring
    keyring.set_password("oapw:bitbucket", username, token)


def load_credential(username: str) -> str | None:
    """Load a Bitbucket API token (or legacy App Password) from the OS keyring."""
    try:
        import keyring
        return keyring.get_password("oapw:bitbucket", username)
    except Exception:
        return None


def build_auth_url(clone_url: str, username: str, token: str) -> str:
    """Inject credentials into an HTTPS clone URL.

    Bitbucket Cloud API tokens use ``x-token-auth:{token}`` as the credential
    pair — the actual username is not used in the URL.

    Bitbucket Server / Data Center still uses ``{username}:{token}``.

    Examples::

        # Cloud (API token)
        https://bitbucket.org/ws/repo.git
            → https://x-token-auth:{token}@bitbucket.org/ws/repo.git

        # Server / DC
        https://selfhosted.company.com/scm/proj/repo.git
            → https://user:{token}@selfhosted.company.com/scm/proj/repo.git
    """
    import urllib.parse
    parsed = urllib.parse.urlparse(clone_url)

    if is_cloud(clone_url):
        # Bitbucket Cloud API token format
        http_user = "x-token-auth"
        http_pass = token
    else:
        # Bitbucket Server / DC — still username:token
        http_user = username
        http_pass = token

    auth = (
        f"{urllib.parse.quote(http_user, safe='')}:"
        f"{urllib.parse.quote(http_pass, safe='')}"
    )
    port_part = f":{parsed.port}" if parsed.port else ""
    authed = parsed._replace(netloc=f"{auth}@{parsed.hostname}{port_part}")
    return urllib.parse.urlunparse(authed)


def is_cloud(url: str) -> bool:
    return "bitbucket.org" in url


def repo_slug(url: str) -> str:
    """Extract a short name from a Bitbucket clone URL.

    https://bitbucket.org/workspace/my-repo.git → "my-repo"
    """
    m = re.search(r"/([^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else "repo"
