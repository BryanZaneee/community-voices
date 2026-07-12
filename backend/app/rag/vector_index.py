"""Dense vector index over a sqlite-vec connection.

Stores embeddings in a vec0 virtual table and chunk metadata + content in a
sibling regular table so retrieval needs no second lookup. The tables live in
the shared community.sqlite file next to the app's relational tables.
"""
from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path
from typing import Iterable

from app.rag.chunker import Chunk


class VectorIndexDependencyError(RuntimeError):
    """Raised when the sqlite-vec package is needed but unavailable."""


def _serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    try:
        import sqlite_vec
    except ModuleNotFoundError as exc:
        raise VectorIndexDependencyError(
            "VectorIndex requires the sqlite-vec package "
            "(pip install -r backend/requirements.txt)."
        ) from exc

    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


class VectorIndex:
    """sqlite-vec backed dense index.

    Schema:
      vec_chunks(rowid, embedding FLOAT[dim])  -- vec0 virtual table
      chunks(chunk_id PK, rowid, path, heading_path JSON, start_line,
             end_line, content, tokens_est)
    """

    def __init__(self, db_path: Path | str, dim: int):
        self.db_path = (
            str(db_path) if db_path != ":memory:" else ":memory:"
        )
        self.dim = dim
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: created in the app lifespan (main thread)
        # but used from FastAPI's request threadpool, same as db.connect().
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            _load_sqlite_vec(conn)
        except Exception:
            conn.close()
            raise
        self._conn = conn
        self._ensure_schema()
        return conn

    def _ensure_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                embedding FLOAT[{self.dim}]
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                rowid INTEGER NOT NULL UNIQUE,
                path TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                content TEXT NOT NULL,
                tokens_est INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
            """
        )
        self._conn.commit()

    def ensure_schema(self) -> None:
        """Open the database and create the vector schema if needed."""
        self._connect()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def add(self, chunk: Chunk, embedding: list[float]) -> None:
        self.add_documents([(chunk, embedding)])

    def add_documents(
        self,
        chunks: Iterable[tuple[Chunk, list[float]]],
    ) -> int:
        """Add a batch of (chunk, embedding) pairs in one transaction."""
        conn = self._connect()
        count = 0
        with conn:
            for chunk, embedding in chunks:
                if len(embedding) != self.dim:
                    raise ValueError(
                        f"embedding dim {len(embedding)} != index dim {self.dim}"
                    )
                self._upsert(conn, chunk, embedding)
                count += 1
        return count

    def _upsert(
        self,
        conn: sqlite3.Connection,
        chunk: Chunk,
        embedding: list[float],
    ) -> None:
        existing = conn.execute(
            "SELECT rowid FROM chunks WHERE chunk_id = ?", (chunk.chunk_id,)
        ).fetchone()
        if existing is None:
            cur = conn.execute(
                "INSERT INTO vec_chunks(embedding) VALUES (?)",
                (_serialize_f32(embedding),),
            )
            rowid = cur.lastrowid
        else:
            rowid = existing["rowid"]
            self._write_vector(conn, rowid, embedding)
        self._write_metadata(conn, rowid, chunk)

    def _write_vector(
        self,
        conn: sqlite3.Connection,
        rowid: int,
        embedding: list[float],
    ) -> None:
        conn.execute("DELETE FROM vec_chunks WHERE rowid = ?", (rowid,))
        conn.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
            (rowid, _serialize_f32(embedding)),
        )

    @staticmethod
    def _write_metadata(
        conn: sqlite3.Connection,
        rowid: int,
        chunk: Chunk,
    ) -> None:
        conn.execute(
            """
            INSERT INTO chunks(chunk_id, rowid, path, heading_path,
                start_line, end_line, content, tokens_est)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                rowid = excluded.rowid,
                path = excluded.path,
                heading_path = excluded.heading_path,
                start_line = excluded.start_line,
                end_line = excluded.end_line,
                content = excluded.content,
                tokens_est = excluded.tokens_est
            """,
            (
                chunk.chunk_id,
                rowid,
                chunk.path,
                json.dumps(list(chunk.heading_path)),
                chunk.start_line,
                chunk.end_line,
                chunk.content,
                chunk.tokens_est,
            ),
        )

    def search(
        self,
        query_embedding: list[float],
        k: int = 5,
    ) -> list[tuple[Chunk, float]]:
        if k <= 0:
            raise ValueError("k must be a positive integer.")
        if len(query_embedding) != self.dim:
            raise ValueError(
                f"query dim {len(query_embedding)} != index dim {self.dim}"
            )
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT v.rowid AS rowid, v.distance AS distance,
                   c.chunk_id, c.path, c.heading_path,
                   c.start_line, c.end_line, c.content, c.tokens_est
            FROM vec_chunks v
            JOIN chunks c ON c.rowid = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_serialize_f32(query_embedding), k),
        ).fetchall()
        out: list[tuple[Chunk, float]] = []
        for row in rows:
            out.append((self._chunk_from_row(row), float(row["distance"])))
        return out

    def all_embeddings(self) -> list[tuple[Chunk, list[float]]]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT c.chunk_id, c.path, c.heading_path,
                   c.start_line, c.end_line, c.content, c.tokens_est,
                   v.embedding AS embedding
            FROM chunks c
            JOIN vec_chunks v ON c.rowid = v.rowid
            ORDER BY c.chunk_id
            """
        ).fetchall()
        out: list[tuple[Chunk, list[float]]] = []
        for row in rows:
            embedding = list(struct.unpack(f"{self.dim}f", row["embedding"]))
            out.append((self._chunk_from_row(row), embedding))
        return out

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> Chunk:
        return Chunk(
            chunk_id=row["chunk_id"],
            path=row["path"],
            heading_path=tuple(json.loads(row["heading_path"])),
            start_line=row["start_line"],
            end_line=row["end_line"],
            content=row["content"],
            tokens_est=row["tokens_est"],
        )

    def __len__(self) -> int:
        conn = self._connect()
        return conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
