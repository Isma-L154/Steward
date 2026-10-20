from steward.github.models import DEPENDABOT_LOGIN, graphql_login


def test_dependabot_login_is_the_rest_bot_name() -> None:
    assert DEPENDABOT_LOGIN == "dependabot[bot]"


def test_graphql_login_drops_the_bot_suffix() -> None:
    assert graphql_login("dependabot[bot]") == "dependabot"
    assert graphql_login("app-steward[bot]") == "app-steward"


def test_graphql_login_keeps_a_user_login() -> None:
    assert graphql_login("Isma-L154") == "Isma-L154"
