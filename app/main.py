"""Board posts API (HIST-288 L3) — single-module FastAPI app backed by SQLite."""

import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

DATABASE = "board.db"


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

SELECT_COLUMNS = "id, title, body, created_at, updated_at"


@app.post("/posts", status_code=201, response_model=Post)
def create_post(payload: PostIn) -> dict:
    ts = now()
    with closing(connect()) as conn:
        cur = conn.execute(
            "INSERT INTO posts (title, body, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (payload.title, payload.body, ts, ts),
        )
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return dict(row)


@app.get("/posts")
def list_posts(
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)
) -> dict:
    with closing(connect()) as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM posts").fetchone()["n"]
        rows = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts ORDER BY id DESC LIMIT ? OFFSET ?",
            (size, (page - 1) * size),
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "size": size,
    }


@app.get("/posts/{post_id}", response_model=Post)
def get_post(post_id: int) -> dict:
    with closing(connect()) as conn:
        row = conn.execute(
            f"SELECT {SELECT_COLUMNS} FROM posts WHERE id = ?", (post_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return dict(row)


@app.put("/posts/{post_id}", response_model=Post)
def update_post(post_id: int, payload: PostIn) -> dict:
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
    return dict(row)


@app.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int) -> Response:
    with closing(connect()) as conn:
        row = conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="post not found")
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    return Response(status_code=204)
