import re
from dataclasses import dataclass

# GitHub logins: letters, digits and single hyphens, at most 39 characters.
_LOGIN = re.compile(r"[A-Za-z0-9](?:-?[A-Za-z0-9])*")
_MAX_LOGIN = 39


class InvalidAccounts(ValueError):
    """The owner or the allowlist is not a list of GitHub logins."""


def _login(value: str) -> str:
    login = value.strip()
    if len(login) > _MAX_LOGIN or _LOGIN.fullmatch(login) is None:
        raise InvalidAccounts
    return login.lower()


def _key(login: str) -> str | None:
    # Logins are ASCII; Unicode case folding would map some other characters onto them.
    return login.lower() if login.isascii() else None


@dataclass(frozen=True)
class Accounts:
    """The accounts Steward acts on: the owner, plus the ones the owner allows. Every other
    installation is ignored."""

    owner: str
    allowed: frozenset[str]

    @classmethod
    def parse(cls, owner: str, allowed: str) -> Accounts:
        listed = [_login(item) for item in allowed.split(",")] if allowed.strip() else []
        owner_login = _login(owner)
        return cls(owner_login, frozenset({owner_login, *listed}))

    def may_act(self, login: str) -> bool:
        return _key(login) in self.allowed

    def is_owner(self, login: str) -> bool:
        return _key(login) == self.owner
