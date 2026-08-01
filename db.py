import sqlite3
import hashlib
import re
from collections import Counter
from datetime import datetime
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db():
    """Create the ScreenshotIndex table and FTS virtual table if they don't exist."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS screenshot_index (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name   TEXT NOT NULL,
                file_path   TEXT NOT NULL UNIQUE,
                file_hash   TEXT NOT NULL,
                created_time TEXT NOT NULL,
                indexed_time TEXT NOT NULL,
                ocr_text    TEXT,
                status      TEXT NOT NULL DEFAULT 'processed',
                error       TEXT
            )
        """)

        # Full-text search virtual table (FTS5) over ocr_text
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS screenshot_fts
            USING fts5(
                file_name,
                ocr_text,
                content='screenshot_index',
                content_rowid='id'
            )
        """)

        # Triggers to keep FTS in sync with the main table
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS idx_ai
            AFTER INSERT ON screenshot_index BEGIN
                INSERT INTO screenshot_fts(rowid, file_name, ocr_text)
                VALUES (new.id, new.file_name, new.ocr_text);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS idx_au
            AFTER UPDATE ON screenshot_index BEGIN
                INSERT INTO screenshot_fts(screenshot_fts, rowid, file_name, ocr_text)
                VALUES ('delete', old.id, old.file_name, old.ocr_text);
                INSERT INTO screenshot_fts(rowid, file_name, ocr_text)
                VALUES (new.id, new.file_name, new.ocr_text);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS idx_ad
            AFTER DELETE ON screenshot_index BEGIN
                INSERT INTO screenshot_fts(screenshot_fts, rowid, file_name, ocr_text)
                VALUES ('delete', old.id, old.file_name, old.ocr_text);
            END
        """)
        conn.commit()


def clear_index():
    """Delete every indexed record so the next scan re-OCRs all files.

    Used by the 'Rebuild index' action to re-process the whole library with an
    updated OCR pipeline. The FTS table is rebuilt from the (now empty) content
    table and the id sequence is reset.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM screenshot_index")
        conn.execute("INSERT INTO screenshot_fts(screenshot_fts) VALUES('rebuild')")
        conn.execute("DELETE FROM sqlite_sequence WHERE name='screenshot_index'")
        conn.commit()


def file_hash(file_path: str) -> str:
    """Return MD5 hash of a file to detect duplicates."""
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_already_indexed(file_path: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM screenshot_index WHERE file_path = ?", (file_path,)
        ).fetchone()
        return row is not None


def is_hash_indexed(hash_val: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM screenshot_index WHERE file_hash = ?", (hash_val,)
        ).fetchone()
        return row is not None


def insert_record(file_path: str, ocr_text: str, file_hash_val: str,
                  status: str = "processed", error: str = None):
    file_name = os.path.basename(file_path)
    now = datetime.now().isoformat(sep=" ", timespec="seconds")
    try:
        import os as _os
        mtime = _os.path.getmtime(file_path)
        created_time = datetime.fromtimestamp(mtime).isoformat(sep=" ", timespec="seconds")
    except Exception:
        created_time = now

    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO screenshot_index
                (file_name, file_path, file_hash, created_time, indexed_time, ocr_text, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (file_name, file_path, file_hash_val, created_time, now, ocr_text, status, error))
        conn.commit()


def search(query: str, limit: int = 10, sort: str = "relevance"):
    """Full-text search using FTS5. Returns list of sqlite3.Row.
    sort='relevance' orders by FTS5 rank; sort='recent' orders by created_time DESC."""
    order_clause = "si.created_time DESC" if sort == "recent" else "rank"

    def _run(match_query: str):
        with get_connection() as conn:
            return conn.execute(f"""
                SELECT
                    si.id,
                    si.file_name,
                    si.file_path,
                    si.created_time,
                    si.indexed_time,
                    snippet(screenshot_fts, 1, '[', ']', '...', 20) AS snippet,
                    si.ocr_text
                FROM screenshot_fts
                JOIN screenshot_index si ON screenshot_fts.rowid = si.id
                WHERE screenshot_fts MATCH ?
                ORDER BY {order_clause}
                LIMIT ?
            """, (match_query, limit)).fetchall()

    def _sanitize_query(raw_query: str) -> str:
        # Convert punctuation-heavy text (e.g. example.com, john@x.com, PRJ-123)
        # into FTS-friendly terms while preserving wildcard suffixes.
        tokens = re.findall(r"[A-Za-z0-9_]+\*?", raw_query)
        return " ".join(tokens)

    def _run_case_insensitive(raw_query: str):
        # Fallback search (case-insensitive) over plain text when FTS query
        # syntax or tokenization doesn't match user expectations.
        tokens = re.findall(r"[A-Za-z0-9_]+", raw_query.lower())
        if not tokens:
            return []

        where_parts = ["lower(coalesce(si.ocr_text, '')) LIKE ?" for _ in tokens]
        where_sql = " AND ".join(where_parts)
        params = [f"%{tok}%" for tok in tokens]
        params.append(limit)

        # This fallback does not join the FTS table, so 'rank' is unavailable.
        # Always order by recency here regardless of the requested sort.
        with get_connection() as conn:
            return conn.execute(f"""
                SELECT
                    si.id,
                    si.file_name,
                    si.file_path,
                    si.created_time,
                    si.indexed_time,
                    substr(coalesce(si.ocr_text, ''), 1, 280) AS snippet,
                    si.ocr_text
                FROM screenshot_index si
                WHERE {where_sql}
                ORDER BY si.created_time DESC
                LIMIT ?
            """, params).fetchall()

    query = (query or "").strip()
    if not query:
        return []

    try:
        rows = _run(query)
        if rows:
            return rows
        return _run_case_insensitive(query)
    except sqlite3.OperationalError as exc:
        err = str(exc).lower()
        if "fts5: syntax error" not in err and "malformed" not in err:
            raise

        sanitized = _sanitize_query(query)
        if not sanitized:
            return _run_case_insensitive(query)

        # Retry with sanitized query to avoid parser errors on punctuation.
        rows = _run(sanitized)
        if rows:
            return rows
        return _run_case_insensitive(query)


def get_stats():
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                                          AS total,
                SUM(status = 'processed')                                         AS processed,
                SUM(status = 'duplicate')                                         AS duplicate,
                SUM(status = 'failed')                                            AS failed,
                SUM(status = 'processed'
                    AND (ocr_text IS NULL OR trim(ocr_text) = ''))                AS no_text,
                SUM(date(indexed_time) = date('now'))                             AS today,
                SUM(date(indexed_time) >= date('now', '-6 days'))                 AS this_week,
                MAX(indexed_time)                                                  AS last_indexed
            FROM screenshot_index
        """).fetchone()
        return {
            "total":       int(row[0] or 0),
            "processed":   int(row[1] or 0),
            "duplicate":   int(row[2] or 0),
            "failed":      int(row[3] or 0),
            "no_text":     int(row[4] or 0),
            "today":       int(row[5] or 0),
            "this_week":   int(row[6] or 0),
            "last_indexed": row[7] or "—",
        }


def get_files_by_filter(filter_key: str, limit: int = 500):
    """Return rows filtered by a named filter key for the stat card drill-down views."""
    filters = {
        "total":     ("1=1", []),
        "ocr":       ("status='processed' AND ocr_text IS NOT NULL AND trim(ocr_text) != ''", []),
        "no_text":   ("status='processed' AND (ocr_text IS NULL OR trim(ocr_text) = '')", []),
        "duplicate": ("status='duplicate'", []),
        "failed":    ("status='failed'", []),
        "today":     ("date(indexed_time)=date('now')", []),
        "this_week": ("date(indexed_time)>=date('now','-6 days')", []),
    }
    where, params = filters.get(filter_key, filters["total"])
    params = list(params) + [limit]
    with get_connection() as conn:
        return conn.execute(f"""
            SELECT id, file_name, file_path, created_time, indexed_time,
                   ocr_text, error, status
            FROM screenshot_index
            WHERE {where}
            ORDER BY indexed_time DESC
            LIMIT ?
        """, params).fetchall()


def path_exists_in_index(file_path: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM screenshot_index WHERE file_path = ? LIMIT 1", (file_path,)
        ).fetchone()
        return row is not None


def get_word_cloud_words(max_words: int = 120, min_len: int = 3):
    """Return top words from OCR text for word-cloud rendering."""
    stop_words = {
        "the", "and", "for", "that", "with", "this", "from", "you", "your", "are",
        "was", "were", "have", "has", "had", "not", "but", "can", "will", "all",
        "our", "out", "into", "about", "there", "their", "they", "them", "what",
        "when", "where", "which", "would", "could", "should", "just", "also", "than",
        "then", "some", "more", "most", "over", "under", "after", "before", "each",
        "only", "other", "such", "any", "many", "may", "new", "get", "set", "use",
        "used", "using", "user", "users", "page", "click", "open", "view", "file",
        "home", "back", "next", "save", "edit", "search", "message", "messages",
        "team", "teams", "meeting", "outlook", "microsoft", "https", "http", "www",
        "com", "net", "org", "img", "png", "jpg", "jpeg", "amp", "inc",
    }

    counter = Counter()

    with get_connection() as conn:
        rows = conn.execute("SELECT ocr_text FROM screenshot_index WHERE ocr_text IS NOT NULL").fetchall()

    for row in rows:
        text = (row["ocr_text"] or "").lower()
        tokens = re.findall(r"[a-z][a-z0-9_\-]+", text)
        for tok in tokens:
            if len(tok) < min_len:
                continue
            if tok in stop_words:
                continue
            if tok.isdigit():
                continue
            counter[tok] += 1

    return counter.most_common(max_words)


import os
