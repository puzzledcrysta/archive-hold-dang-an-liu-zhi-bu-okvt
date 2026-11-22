import sqlite3
from contextlib import contextmanager
from pathlib import Path
from app import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, source BLOB NOT NULL, book BLOB NOT NULL,
  result TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  run_id TEXT NOT NULL REFERENCES runs(id), version INTEGER NOT NULL,
  decision TEXT NOT NULL, note TEXT NOT NULL, changed TEXT NOT NULL,
  PRIMARY KEY(run_id,version)
);
CREATE TABLE IF NOT EXISTS rosters (
  id TEXT PRIMARY KEY, source BLOB NOT NULL, revision BLOB NOT NULL,
  result TEXT NOT NULL, created TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS active_roster (
  slot TEXT PRIMARY KEY, roster_id TEXT NOT NULL REFERENCES rosters(id),
  switched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS roster_history (
  roster_id TEXT NOT NULL REFERENCES rosters(id), archived_at TEXT NOT NULL,
  note TEXT NOT NULL
);
"""


@contextmanager
def connection():
    path = Path(settings.DB)
    path.parent.mkdir(parents=True,exist_ok=True)
    db = sqlite3.connect(path,timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript(SCHEMA)
        with db:
            yield db
    finally:
        db.close()
