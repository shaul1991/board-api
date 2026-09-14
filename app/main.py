"""Board posts API (HIST-288 L3) — single-module FastAPI app backed by SQLite."""

import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

DATABASE = os.environ.get("BOARD_DB", "board.db")
MAX_BODY_BYTES = 1024 * 1024  # 1 MiB request body cap


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.isolation_level = None  # autocommit; every statement is single-statement
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)


class Post(PostIn):
    id: int
    created_at: str
    updated_at: str


class PostList(BaseModel):
    items: list[Post]
    total: int
    page: int
    size: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


class BodySizeLimitMiddleware:
    """Pure-ASGI middleware: 413 once received http.request bytes pass the cap."""

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise HTTPException(
                        status_code=413, detail="request body too large"
                    )
            return message

        await self.app(scope, limited_receive, send)


app = FastAPI(lifespan=lifespan)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)

SELECT_COLUMNS = "id, title, body, created_at, updated_at"


@app.post("/posts", status_code=201, response_model=Post)
def create_post(payload: PostIn) -> Post:
    ts = now()
    with closing(connect()) as conn:
        cur = conn.execute(
            "INSERT INTO posts (title, body, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (payload.title, payload.body, ts, ts),
        )
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return Post(**dict(row))


@app.get("/posts", response_model=PostList)
def list_posts(
    page: int = Query(1, ge=1, le=1000000), size: int = Query(20, ge=1, le=100)
) -> PostList:
    with closing(connect()) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        rows = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts ORDER BY id DESC LIMIT ? OFFSET ?",
            (size, (page - 1) * size),
        ).fetchall()
    return PostList(
        items=[dict(row) for row in rows], total=total, page=page, size=size
    )


@app.get("/posts/{post_id}", response_model=Post)
def get_post(post_id: int) -> Post:
    with closing(connect()) as conn:
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return Post(**dict(row))


@app.put("/posts/{post_id}", response_model=Post)
def update_post(post_id: int, payload: PostIn) -> Post:
    ts = now()
    with closing(connect()) as conn:
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="post not found")
        conn.execute(
            "UPDATE posts SET title = ?, body = ?, updated_at = ? WHERE id = ?",
            (payload.title, payload.body, ts, post_id),
        )
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
    return Post(**dict(row))


@app.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int) -> Response:
    with closing(connect()) as conn:
        row = conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="post not found")
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    return Response(status_code=204)
