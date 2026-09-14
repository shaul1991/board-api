"""Pins the observable HTTP contract of the board posts API (HIST-288 L3)."""

import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATABASE", str(tmp_path / "test.db"))
    with TestClient(main.app) as c:
        yield c


def create(client, title="t", body="b"):
    resp = client.post("/posts", json={"title": title, "body": body})
    assert resp.status_code == 201
    return resp.json()


# Story 1: create
def test_create_post(client):
    post = create(client, title="hello", body="world")
    assert post["id"] >= 1
    assert post["title"] == "hello"
    assert post["body"] == "world"
    assert post["created_at"]
    assert post["created_at"] == post["updated_at"]


# Story 2: read
def test_read_post(client):
    post = create(client)
    resp = client.get(f"/posts/{post['id']}")
    assert resp.status_code == 200
    assert resp.json() == post


# Story 3: list with 1-based paging, newest first
def test_list_pagination_newest_first(client):
    first = create(client, title="first", body="1")
    second = create(client, title="second", body="2")
    third = create(client, title="third", body="3")

    page1 = client.get("/posts", params={"page": 1, "size": 2})
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 3
    assert body1["page"] == 1
    assert body1["size"] == 2
    assert [p["id"] for p in body1["items"]] == [third["id"], second["id"]]

    page2 = client.get("/posts", params={"page": 2, "size": 2})
    assert page2.status_code == 200
    assert [p["id"] for p in page2.json()["items"]] == [first["id"]]


# Story 4: update
def test_update_post(client):
    post = create(client, title="old", body="old body")
    resp = client.put(f"/posts/{post['id']}", json={"title": "new", "body": "new body"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["id"] == post["id"]
    assert updated["title"] == "new"
    assert updated["body"] == "new body"
    assert updated["created_at"] == post["created_at"]
    assert updated["updated_at"] != post["updated_at"]


# Story 5: delete
def test_delete_post(client):
    post = create(client)
    resp = client.delete(f"/posts/{post['id']}")
    assert resp.status_code == 204
    assert resp.content == b""
    assert client.get(f"/posts/{post['id']}").status_code == 404


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_missing_post_404(client, method):
    kwargs = {}
    if method == "put":
        kwargs["json"] = {"title": "t", "body": "b"}
    resp = getattr(client, method)("/posts/999999", **kwargs)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "post not found"}


def test_pagination_bounds(client):
    assert client.get("/posts", params={"size": 101}).status_code == 422
    assert client.get("/posts", params={"size": 0}).status_code == 422
    assert client.get("/posts", params={"page": 0}).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "", "body": "b"},
        {"title": "t", "body": ""},
    ],
)
def test_validation_422_empty_title_or_body(client, payload):
    assert client.post("/posts", json=payload).status_code == 422
