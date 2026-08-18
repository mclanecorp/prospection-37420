"""Accès SQLite : schéma, connexion et petits helpers de lecture."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Un compte = une Page Facebook ou un compte Instagram professionnel.
CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    platform     TEXT NOT NULL,            -- 'facebook' | 'instagram'
    external_id  TEXT NOT NULL,            -- id de la Page / de l'utilisateur IG
    name         TEXT NOT NULL,
    access_token TEXT NOT NULL,
    page_id      TEXT,                     -- Page reliée, pour Instagram
    active       INTEGER NOT NULL DEFAULT 1,
    connected_at TEXT NOT NULL,
    UNIQUE (platform, external_id)
);

CREATE TABLE IF NOT EXISTS publications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft|scheduled|published|partial|failed
    scheduled_at TEXT,                           -- UTC ISO, si publication différée
    created_at   TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS media (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id INTEGER NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    filename       TEXT NOT NULL,
    mime           TEXT NOT NULL,
    token          TEXT NOT NULL UNIQUE,   -- jeton d'URL publique, non devinable
    position       INTEGER NOT NULL DEFAULT 0
);

-- Une cible = l'exemplaire d'une publication sur un compte donné.
CREATE TABLE IF NOT EXISTS targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id  INTEGER NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|published|failed
    external_post_id TEXT,
    permalink       TEXT,
    error           TEXT,
    published_at    TEXT,
    UNIQUE (publication_id, account_id)
);

-- Une photo des compteurs à un instant donné : c'est ce qui permet de tracer
-- les courbes d'évolution.
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id   INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    captured_at TEXT NOT NULL,
    views       INTEGER,
    reach       INTEGER,
    likes       INTEGER,
    comments    INTEGER,
    shares      INTEGER,
    saves       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshots_target ON snapshots(target_id, captured_at);

CREATE TABLE IF NOT EXISTS fb_groups (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    url      TEXT NOT NULL DEFAULT '',
    active   INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL DEFAULT 0
);

-- Suivi du partage manuel dans les groupes (l'API Groupes n'existe plus).
CREATE TABLE IF NOT EXISTS group_shares (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    publication_id INTEGER NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    group_id       INTEGER NOT NULL REFERENCES fb_groups(id) ON DELETE CASCADE,
    shared_at      TEXT,
    manual_views   INTEGER,
    UNIQUE (publication_id, group_id)
);
"""


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA journal_mode = WAL')
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init():
    config.ensure_dirs()
    with session() as conn:
        conn.executescript(SCHEMA)


def get_setting(conn, key, default=None):
    row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def set_setting(conn, key, value):
    conn.execute(
        'INSERT INTO settings (key, value) VALUES (?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, value),
    )


def active_accounts(conn):
    return conn.execute(
        'SELECT * FROM accounts WHERE active = 1 ORDER BY platform, name'
    ).fetchall()


def latest_snapshot(conn, target_id):
    return conn.execute(
        'SELECT * FROM snapshots WHERE target_id = ? ORDER BY captured_at DESC LIMIT 1',
        (target_id,),
    ).fetchone()
