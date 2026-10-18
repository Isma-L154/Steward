from steward.repos import IGNORE_TOPIC, is_managed


def test_ignore_topic() -> None:
    assert IGNORE_TOPIC == "steward-ignore"


def test_plain_repository_is_managed() -> None:
    assert is_managed(archived=False, topics=[])


def test_archived_repository_is_not_managed() -> None:
    assert not is_managed(archived=True, topics=[])


def test_repository_with_the_ignore_topic_is_not_managed() -> None:
    assert not is_managed(archived=False, topics=["python", "steward-ignore"])
