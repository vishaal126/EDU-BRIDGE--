"""Database schema and shared constants.

Timestamps are stored as ISO-8601 UTC text so the same schema runs on SQLite and PostgreSQL.
{PK} is replaced by the dialect-specific auto-increment primary key.
"""
from dataclasses import dataclass

ROLE_STUDENT, ROLE_TUTOR = "student", "tutor"
ROLES = ("student", "tutor")
CONN_PENDING, CONN_ACCEPTED, CONN_REJECTED = "pending", "accepted", "rejected"
SKILL_TEACH, SKILL_LEARN = "teach", "learn"
MAX_GROUP_SIZE = 3

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id {PK},
        email TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        password_hash TEXT,
        role TEXT NOT NULL CHECK (role IN ('student','tutor')),
        avatar BLOB,
        avatar_mime TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS auth_identities (
        id {PK},
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider TEXT NOT NULL,
        provider_user_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (provider, provider_user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS password_resets (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS oauth_states (
        state TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS student_profiles (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        bio TEXT NOT NULL DEFAULT '',
        interests TEXT NOT NULL DEFAULT '',
        education TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS tutor_profiles (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        headline TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        subjects TEXT NOT NULL DEFAULT '',
        skills TEXT NOT NULL DEFAULT '',
        experience_years INTEGER NOT NULL DEFAULT 0,
        qualifications TEXT NOT NULL DEFAULT '',
        availability TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        is_published INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS connections (
        id {PK},
        student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        tutor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        intro_message TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        responded_at TEXT,
        UNIQUE (student_id, tutor_id)
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id {PK},
        connection_id INTEGER NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
        sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS skills (
        id {PK},
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        name_norm TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('teach','learn')),
        created_at TEXT NOT NULL,
        UNIQUE (user_id, name_norm, kind)
    )""",
    """CREATE TABLE IF NOT EXISTS exchange_groups (
        id {PK},
        name TEXT NOT NULL,
        creator_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        completed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS group_members (
        id {PK},
        group_id INTEGER NOT NULL REFERENCES exchange_groups(id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        status TEXT NOT NULL,
        invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL,
        UNIQUE (group_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS group_messages (
        id {PK},
        group_id INTEGER NOT NULL REFERENCES exchange_groups(id) ON DELETE CASCADE,
        sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS learning_sessions (
        id {PK},
        group_id INTEGER NOT NULL REFERENCES exchange_groups(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        scheduled_at TEXT NOT NULL,
        duration_min INTEGER NOT NULL DEFAULT 60,
        meeting_link TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'scheduled',
        created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS exchange_feedback (
        id {PK},
        group_id INTEGER NOT NULL REFERENCES exchange_groups(id) ON DELETE CASCADE,
        from_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        to_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
        comment TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        UNIQUE (group_id, from_user_id, to_user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS notifications (
        id {PK},
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL DEFAULT '',
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_conversations (
        id {PK},
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_messages (
        id {PK},
        conversation_id INTEGER NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('user','assistant')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_msgs_conn ON messages(connection_id)",
    "CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read)",
    "CREATE INDEX IF NOT EXISTS idx_skills_user ON skills(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_gm_user ON group_members(user_id)",
]


@dataclass
class User:
    id: int
    email: str
    full_name: str
    role: str
