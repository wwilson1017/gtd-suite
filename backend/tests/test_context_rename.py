"""Renaming a context: every todo of the list that carries it moves, finished ones
included, another list's identical context is untouched, and a merge into an
existing context waits for the confirmation."""

import pytest

from backend import common, lists, service


def _todo(list_id, context, status="next_action"):
    return service.create_todo(list_id, "bake", context=context, status=status)


def test_rename_moves_all_of_the_lists_todos_and_nobody_elses(L):
    other = lists.create_list("UTC")["list_id"]
    open_one = _todo(L, "@Baking")
    _todo(L, "@Baking", status="done")
    office = _todo(L, "TK Office")
    theirs = _todo(other, "@Baking")

    assert service.rename_context(L, "@Baking", " Baking ") == {
        "old": "@Baking",
        "new": "Baking",
        "updated": 2,
        "merged": False,
    }

    assert service.get_filters(L)["contexts"] == ["Baking", "TK Office"]
    assert service.get_filters(other)["contexts"] == ["@Baking"]
    after = service.get_todo(L, open_one["id"])
    assert after["context"] == "Baking"
    assert after["updated_at"] == open_one["updated_at"]  # a rename is not an edit
    assert service.get_todo(L, office["id"])["context"] == "TK Office"
    assert service.get_todo(other, theirs["id"])["context"] == "@Baking"


def test_merge_into_an_existing_context_waits_for_the_confirmation(L):
    a = _todo(L, "@Baking")
    _todo(L, "Baking")

    with pytest.raises(common.ConflictError, match='already have a context named "Baking"'):
        service.rename_context(L, "@Baking", "Baking")
    assert service.get_todo(L, a["id"])["context"] == "@Baking"

    result = service.rename_context(L, "@Baking", "Baking", merge=True)
    assert (result["updated"], result["merged"]) == (1, True)
    assert service.get_filters(L)["contexts"] == ["Baking"]


def test_a_context_the_list_does_not_have_is_not_found(L):
    other = lists.create_list("UTC")["list_id"]
    _todo(other, "@Baking")
    with pytest.raises(common.NotFoundError):
        service.rename_context(L, "@Baking", "Baking")


@pytest.mark.parametrize(
    "old, new, message",
    [
        ("", "Baking", "context is required"),
        ("@Baking", "  ", "new name cannot be empty"),
        ("@Baking", "@Baking", "already named"),
        ("@Baking", "x" * 501, "new name too long"),
    ],
)
def test_bad_names_are_refused(L, old, new, message):
    _todo(L, "@Baking")
    with pytest.raises(common.ValidationError, match=message):
        service.rename_context(L, old, new)


def test_over_http_a_conflict_is_409_until_merge_is_sent(new_list):
    made = new_list()
    c, api = made["client"], made["api"]
    for context in ("@Baking", "Baking"):
        c.post(f"{api}/todos", json={"title": "bake", "context": context})

    res = c.post(f"{api}/contexts/rename", json={"old": "@Baking", "new": "Baking"})
    assert res.status_code == 409 and res.headers["cache-control"] == "no-store"
    assert res.json()["detail"].startswith('You already have a context named "Baking"')
    assert c.get(f"{api}/filters").json()["contexts"] == ["@Baking", "Baking"]

    res = c.post(f"{api}/contexts/rename", json={"old": "@Baking", "new": "Baking", "merge": True})
    assert res.json() == {"old": "@Baking", "new": "Baking", "updated": 1, "merged": True}
    assert c.get(f"{api}/filters").json()["contexts"] == ["Baking"]
    assert c.post(f"{api}/contexts/rename", json={"old": "@Baking", "new": "Other"}).status_code == 404
    assert c.post(f"{api}/contexts/rename", json={"old": "Baking", "new": ""}).status_code == 400
