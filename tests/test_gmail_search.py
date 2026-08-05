"""Tests for Gmail message search (offline, no real network).

Every test drives a fake ``googleapiclient`` service, so what is asserted is
the REQUEST the code decides to make — the query it passes, the format it asks
for, how far it paginates, when it stops — and how it behaves when a single
message cannot be read. Nothing here echoes a mock's return value back at
itself.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from ai_assistant.integrations import gmail


class FakeMessagesApi:
    """A ``users().messages()`` stand-in that records every call.

    ``list_pages`` is served in order, one per ``list()`` call. ``get`` serves
    a full message per id, or raises whatever ``get_errors`` holds for that id.
    """

    def __init__(self, list_pages, messages=None, get_errors=None):
        self.list_pages = list(list_pages)
        self.messages = messages or {}
        self.get_errors = get_errors or {}
        self.list_calls = []
        self.get_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        page = self.list_pages.pop(0) if self.list_pages else {}
        return Mock(execute=Mock(return_value=page))

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        message_id = kwargs.get("id")
        if message_id in self.get_errors:
            raise self.get_errors[message_id]
        payload = self.messages.get(
            message_id, {"id": message_id, "payload": {"mimeType": "multipart/mixed"}}
        )
        return Mock(execute=Mock(return_value=payload))


def fake_service(messages_api: FakeMessagesApi) -> Mock:
    service = Mock()
    service.users.return_value.messages.return_value = messages_api
    return service


def stubs(*ids) -> list:
    """What ``messages.list`` really returns: id/threadId stubs, no content."""
    return [{"id": message_id, "threadId": f"t_{message_id}"} for message_id in ids]


def test_search_passes_the_query_through_to_messages_list():
    api = FakeMessagesApi([{"messages": stubs("m1")}])

    gmail.search_messages(
        "from:notifications has:attachment", max_results=5, service=fake_service(api)
    )

    assert api.list_calls[0]["userId"] == "me"
    assert api.list_calls[0]["q"] == "from:notifications has:attachment"
    assert api.list_calls[0]["maxResults"] == 5
    # First page must not carry a page token.
    assert "pageToken" not in api.list_calls[0]


def test_each_hit_is_fetched_with_format_full():
    """``format="full"`` is load-bearing: audio discovery walks payload.parts."""
    api = FakeMessagesApi([{"messages": stubs("m1", "m2")}])

    gmail.search_messages("subject:Meeting", service=fake_service(api))

    assert [call["id"] for call in api.get_calls] == ["m1", "m2"]
    assert all(call["format"] == "full" for call in api.get_calls)
    assert all(call["userId"] == "me" for call in api.get_calls)


def test_search_returns_the_full_messages_not_the_stubs():
    full = {
        "id": "m1",
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [{"mimeType": "audio/mpeg"}],
        },
    }
    api = FakeMessagesApi([{"messages": stubs("m1")}], messages={"m1": full})

    result = gmail.search_messages("q", service=fake_service(api))

    assert result == [full]
    assert "parts" in result[0]["payload"]


def test_pagination_follows_next_page_token():
    api = FakeMessagesApi(
        [
            {"messages": stubs("m1", "m2"), "nextPageToken": "PAGE2"},
            {"messages": stubs("m3")},
        ]
    )

    result = gmail.search_messages("q", max_results=10, service=fake_service(api))

    assert len(api.list_calls) == 2
    assert api.list_calls[1]["pageToken"] == "PAGE2"
    assert [message["id"] for message in result] == ["m1", "m2", "m3"]


def test_pagination_never_exceeds_max_results_even_mid_page():
    """A page may over-deliver; the cap still holds, and no extra get() runs."""
    api = FakeMessagesApi(
        [{"messages": stubs("m1", "m2", "m3", "m4"), "nextPageToken": "PAGE2"}]
    )

    result = gmail.search_messages("q", max_results=3, service=fake_service(api))

    assert len(result) == 3
    assert [call["id"] for call in api.get_calls] == ["m1", "m2", "m3"]
    assert len(api.list_calls) == 1  # cap reached, second page never requested


def test_later_pages_only_ask_for_the_remaining_headroom():
    api = FakeMessagesApi(
        [
            {"messages": stubs("m1", "m2"), "nextPageToken": "PAGE2"},
            {"messages": stubs("m3")},
        ]
    )

    gmail.search_messages("q", max_results=4, service=fake_service(api))

    assert api.list_calls[0]["maxResults"] == 4
    assert api.list_calls[1]["maxResults"] == 2


def test_page_size_is_capped_at_the_api_maximum():
    api = FakeMessagesApi([{"messages": stubs("m1")}])

    gmail.search_messages("q", max_results=5000, service=fake_service(api))

    assert api.list_calls[0]["maxResults"] == gmail.GMAIL_MAX_PAGE_SIZE


def test_one_unreadable_message_does_not_sink_the_search():
    api = FakeMessagesApi(
        [{"messages": stubs("m1", "boom", "m3")}],
        get_errors={"boom": RuntimeError("HttpError 404")},
    )

    result = gmail.search_messages("q", service=fake_service(api))

    assert [message["id"] for message in result] == ["m1", "m3"]


def test_a_failing_list_call_propagates():
    """A broken search must be loud, not silently "no meetings today"."""
    service = Mock()
    service.users.return_value.messages.return_value.list.side_effect = RuntimeError(
        "invalid_grant"
    )

    with pytest.raises(RuntimeError, match="invalid_grant"):
        gmail.search_messages("q", service=service)


def test_no_hits_returns_an_empty_list():
    api = FakeMessagesApi([{"resultSizeEstimate": 0}])

    assert gmail.search_messages("q", service=fake_service(api)) == []
    assert api.get_calls == []


def test_empty_page_stops_pagination_even_with_a_token():
    """Gmail can hand back a token with no messages; don't loop on it."""
    api = FakeMessagesApi([{"messages": [], "nextPageToken": "PAGE2"}])

    assert gmail.search_messages("q", service=fake_service(api)) == []
    assert len(api.list_calls) == 1


def test_zero_max_results_makes_no_request_at_all():
    api = FakeMessagesApi([{"messages": stubs("m1")}])

    assert gmail.search_messages("q", max_results=0, service=fake_service(api)) == []
    assert api.list_calls == []


def test_malformed_stubs_are_ignored():
    api = FakeMessagesApi([{"messages": [{"threadId": "t"}, None, {"id": "m2"}]}])

    result = gmail.search_messages("q", service=fake_service(api))

    assert [message["id"] for message in result] == ["m2"]


def test_search_builds_a_service_when_none_is_given(monkeypatch):
    api = FakeMessagesApi([{"messages": stubs("m1")}])
    built = fake_service(api)
    monkeypatch.setattr(gmail, "build_service", lambda: built)

    result = gmail.search_messages("q")

    assert [message["id"] for message in result] == ["m1"]
