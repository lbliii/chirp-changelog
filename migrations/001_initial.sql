CREATE TABLE release_notes (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'published')),
    release_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE release_tags (
    release_id TEXT NOT NULL REFERENCES release_notes(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (release_id, tag)
);

CREATE INDEX idx_release_notes_timeline
    ON release_notes(status, release_date DESC, created_at DESC);
CREATE INDEX idx_release_tags_tag ON release_tags(tag, release_id);
