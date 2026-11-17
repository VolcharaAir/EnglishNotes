"""Additive SQLite schema: no changes to existing lesson/note values."""

STATEMENTS = (
    "CREATE TABLE cloud_runtime(id INTEGER PRIMARY KEY CHECK(id=1),remote INTEGER NOT NULL)",
    "INSERT INTO cloud_runtime VALUES(1,0)",
    """CREATE TABLE cloud_lessons(
        local_id TEXT PRIMARY KEY REFERENCES lessons(id), remote_id TEXT UNIQUE,
        account_id TEXT, owner_id TEXT, status TEXT NOT NULL DEFAULT 'pending')""",
    """CREATE TABLE cloud_commands(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
        local_id TEXT REFERENCES lessons(id), account_id TEXT, vault_key TEXT)""",
    "CREATE UNIQUE INDEX cloud_command_kind ON cloud_commands(kind,local_id)",
    """CREATE TABLE cloud_notes(note_id TEXT PRIMARY KEY REFERENCES notes(id),
        server_revision INTEGER NOT NULL DEFAULT 0, author_id TEXT, position INTEGER NOT NULL,
        base_json TEXT)""",
    """CREATE TABLE cloud_outbox(note_id TEXT PRIMARY KEY REFERENCES notes(id),
        operation_id TEXT NOT NULL UNIQUE, local_revision INTEGER NOT NULL,
        base_revision INTEGER NOT NULL, payload TEXT NOT NULL, error TEXT)""",
    """CREATE TABLE cloud_inflight(note_id TEXT PRIMARY KEY REFERENCES notes(id),
        operation_id TEXT NOT NULL UNIQUE, local_revision INTEGER NOT NULL,
        base_revision INTEGER NOT NULL, payload TEXT NOT NULL, remote_id TEXT NOT NULL)""",
    """CREATE TABLE cloud_inbox(kind TEXT NOT NULL, remote_id TEXT NOT NULL,
        account_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,remote_id,account_id))""",
    "CREATE TABLE cloud_cursors(account_id TEXT PRIMARY KEY, cursor INTEGER NOT NULL DEFAULT 0)",
    """CREATE TABLE cloud_conflicts(note_id TEXT PRIMARY KEY REFERENCES notes(id),
        base_json TEXT, local_json TEXT NOT NULL, remote_json TEXT NOT NULL,
        server_revision INTEGER NOT NULL)""",
    """CREATE TABLE cloud_conflict_archive(id TEXT PRIMARY KEY, note_id TEXT NOT NULL,
        versions_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
)

QUEUE_SQL = """
 INSERT OR IGNORE INTO cloud_notes(note_id,author_id,position)
 SELECT NEW.id,l.account_id,COALESCE((SELECT MAX(m.position)+1 FROM cloud_notes m
  JOIN notes n ON n.id=m.note_id WHERE n.lesson_id=NEW.lesson_id),0)
 FROM cloud_lessons l WHERE l.local_id=NEW.lesson_id;
 INSERT INTO cloud_outbox(note_id,operation_id,local_revision,base_revision,payload)
 SELECT NEW.id,lower(hex(randomblob(16))),NEW.revision,m.server_revision,
  json_object('title',NEW.title,'content',NEW.content,'deleted',NEW.deleted_at IS NOT NULL,
              'position',m.position)
 FROM cloud_notes m WHERE m.note_id=NEW.id
 ON CONFLICT(note_id) DO UPDATE SET operation_id=excluded.operation_id,
 local_revision=excluded.local_revision,base_revision=excluded.base_revision,
 payload=excluded.payload,error=NULL;
"""

STATEMENTS += tuple(
    f"""CREATE TRIGGER cloud_note_{event.lower()} AFTER {event} ON notes
    WHEN (SELECT remote FROM cloud_runtime WHERE id=1)=0
     AND EXISTS(SELECT 1 FROM cloud_lessons WHERE local_id=NEW.lesson_id)
    BEGIN {QUEUE_SQL} END"""
    for event in ("INSERT", "UPDATE")
)
