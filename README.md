# board-api

HIST-288 L3: minimal board posts API. FastAPI + SQLite in a single module —
no auth, no comments, no ORM, no config. Just the five user stories:
create, read, list with paging, update, delete.

## 용어 (Ubiquitous Language)

| Term | Meaning |
|------|---------|
| Post (게시글) | A single board post. |
| posts | The collection of Posts; also the resource path (`/posts`). |
| title (제목) | Required Post heading, 1–200 chars. |
| body (본문) | Required Post content, 1–10000 chars. |

Code, endpoints, the smoke script, and this README use only these terms —
no synonyms (e.g. "article"/"entry") anywhere.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --port 8000
```

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs
- Data persists in `board.db` (SQLite, created next to `app/` on first boot).

## Endpoints

| Method | Path | Description | Success | Errors |
|--------|------|-------------|---------|--------|
| POST | `/posts` | Create a post (`{"title", "body"}`) | 201 + post | 422 invalid body |
| GET | `/posts/{id}` | Read one post | 200 + post | 404 not found |
| GET | `/posts?page=&size=` | List posts, newest first (`id` desc), 1-based page, size default 20 / max 100 | 200 + `{"items", "total", "page", "size"}` | 422 invalid paging |
| PUT | `/posts/{id}` | Replace title/body, advance `updated_at` | 200 + post | 404 not found, 422 invalid body |
| DELETE | `/posts/{id}` | Delete a post | 204 (empty body) | 404 not found |

- `title`: 1–200 chars, required. `body`: 1–10000 chars, required.
- Timestamps are UTC ISO-8601 strings; on create `created_at == updated_at`.

## curl examples

```bash
# create
curl -s -X POST http://127.0.0.1:8000/posts \
  -H 'Content-Type: application/json' \
  -d '{"title":"hello","body":"world"}'

# read
curl -s http://127.0.0.1:8000/posts/1

# list (page 2, 10 per page)
curl -s 'http://127.0.0.1:8000/posts?page=2&size=10'

# update
curl -s -X PUT http://127.0.0.1:8000/posts/1 \
  -H 'Content-Type: application/json' \
  -d '{"title":"hi","body":"again"}'

# delete
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE http://127.0.0.1:8000/posts/1
```

## Smoke test

```bash
bash scripts/smoke.sh
```

Boots its own uvicorn on port 8000 (port must be free) and, over real HTTP
with `curl` + `jq`, checks:

- story 1: create → 201 with id, `created_at == updated_at`
- story 2: read → 200 after a server restart (persistence)
- story 3: list → 200 with paging (`page`/`size`), newest first
- story 4: update → 200, `updated_at` advanced, `created_at` kept
- story 5: delete → 204 empty body, then read → 404
- 404 responses for GET and DELETE of a nonexistent post

Uses `.venv/bin/python` if present, else `python3`. Exits non-zero on the
first failed check; prints `ALL SMOKE CHECKS PASSED` when fully green.

## Tests

```bash
pytest
```

One test file, `tests/test_posts.py`, pins the HTTP contract — stories 1–5,
404 on read/update/delete of missing ids, pagination bounds (`size` cap,
`page`/`size` >= 1), and 422 validation for empty title/body — against a
temporary SQLite database, so it never touches `board.db`.

