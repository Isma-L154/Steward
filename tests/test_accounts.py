import pytest
from hypothesis import given
from hypothesis import strategies as st

from steward.accounts import Accounts, InvalidAccounts


def test_empty_allowlist_means_the_owner_only() -> None:
    accounts = Accounts.parse("Isma-L154", "")
    assert accounts.may_act("Isma-L154")
    assert not accounts.may_act("Wal-014")


def test_listed_accounts_may_act_but_are_not_the_owner() -> None:
    accounts = Accounts.parse("Isma-L154", " Wal-014 , other-1 ")
    assert accounts.may_act("Wal-014")
    assert accounts.may_act("other-1")
    assert not accounts.is_owner("Wal-014")
    assert accounts.is_owner("Isma-L154")


def test_logins_compare_without_case() -> None:
    accounts = Accounts.parse("Isma-L154", "wal-014")
    assert accounts.may_act("WAL-014")
    assert accounts.is_owner("isma-l154")


def test_an_unlisted_account_may_not_act() -> None:
    accounts = Accounts.parse("Isma-L154", "Wal-014")
    assert not accounts.may_act("Wal-0144")
    assert not accounts.may_act("")
    assert not accounts.is_owner("Wal-014")


@pytest.mark.parametrize(
    ("owner", "allowed"),
    [
        ("", ""),
        ("Isma L154", ""),
        ("Isma-L154", "Wal-014,,other"),
        ("Isma-L154", "-leading"),
        ("Isma-L154", "a" * 40),
        ("Isma-L154", "*"),
    ],
)
def test_anything_but_logins_is_refused(owner: str, allowed: str) -> None:
    with pytest.raises(InvalidAccounts):
        Accounts.parse(owner, allowed)


def test_unicode_that_folds_onto_a_login_is_not_that_login() -> None:
    accounts = Accounts.parse("Isma-L154", "kelvin")
    assert not accounts.may_act(chr(0x212A) + "elvin")


@given(login=st.text(max_size=45))
def test_only_the_owner_and_listed_logins_may_act(login: str) -> None:
    accounts = Accounts.parse("Isma-L154", "Wal-014")
    expected = login.isascii() and login.lower() in {"isma-l154", "wal-014"}
    assert accounts.may_act(login) == expected
