"""Database manager for conversation history using SQLite."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any


class HistoryDB:
    """Manage conversation history in SQLite database."""

    def __init__(self, db_path: Path | None = None):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file. Defaults to ~/.miniagent/history.db
        """
        if db_path is None:
            db_path = Path.home() / ".miniagent" / "history.db"
        
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a new database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Create conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT 'default',
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_session 
                ON conversations(session_id, timestamp)
            """)
            
            # Create sessions table for metadata
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    message_count INTEGER DEFAULT 0
                )
            """)
            
            conn.commit()
        finally:
            conn.close()

    def save_message(
        self,
        role: str,
        content: str,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None
    ) -> int:
        """Save a message to the database.
        
        Args:
            role: 'user' or 'assistant'
            content: Message content
            session_id: Session identifier
            metadata: Optional metadata (e.g., matched skills, tool calls)
            
        Returns:
            ID of the inserted message
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Insert message
            cursor.execute(
                """
                INSERT INTO conversations (session_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, json.dumps(metadata) if metadata else None)
            )
            
            # Update session metadata
            cursor.execute(
                """
                INSERT INTO sessions (session_id, title, updated_at, message_count)
                VALUES (?, ?, CURRENT_TIMESTAMP, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = CURRENT_TIMESTAMP,
                    message_count = message_count + 1
                """,
                (session_id, f"Session {session_id}")
            )
            
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def save_conversation_pair(
        self,
        user_input: str,
        assistant_response: str,
        session_id: str = "default",
        metadata: dict[str, Any] | None = None
    ) -> tuple[int, int]:
        """Save a user-assistant message pair.
        
        Args:
            user_input: User's message
            assistant_response: Assistant's response
            session_id: Session identifier
            metadata: Optional metadata
            
        Returns:
            Tuple of (user_msg_id, assistant_msg_id)
        """
        user_id = self.save_message("user", user_input, session_id, metadata)
        assistant_id = self.save_message("assistant", assistant_response, session_id, metadata)
        return user_id, assistant_id

    def get_history(
        self,
        session_id: str = "default",
        limit: int = 100,
        offset: int = 0
    ) -> list[dict[str, Any]]:
        """Retrieve conversation history.
        
        Args:
            session_id: Session identifier
            limit: Maximum number of messages to retrieve
            offset: Number of messages to skip
            
        Returns:
            List of message dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, role, content, timestamp, metadata
                FROM conversations
                WHERE session_id = ?
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset)
            )
            
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else None
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_recent_conversations(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent conversation sessions.
        
        Args:
            limit: Maximum number of sessions to retrieve
            
        Returns:
            List of session summaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT session_id, title, created_at, updated_at, message_count
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            
            rows = cursor.fetchall()
            return [
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "message_count": row["message_count"]
                }
                for row in rows
            ]
        finally:
            conn.close()

    def clear_history(self, session_id: str = "default") -> None:
        """Clear conversation history for a session.
        
        Args:
            session_id: Session identifier
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM conversations WHERE session_id = ?",
                (session_id,)
            )
            cursor.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (session_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def delete_message(self, message_id: int) -> None:
        """Delete a specific message.
        
        Args:
            message_id: Message ID to delete
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM conversations WHERE id = ?",
                (message_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def get_message_count(self, session_id: str = "default") -> int:
        """Get total message count for a session.

        Args:
            session_id: Session identifier

        Returns:
            Number of messages
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM conversations WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            return row["count"] if row else 0
        finally:
            conn.close()

    def update_session_title(self, session_id: str, title: str) -> None:
        """Update the title of a session.

        Args:
            session_id: Session identifier
            title: New title for the session
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (title, session_id)
            )
            conn.commit()
        finally:
            conn.close()

    def get_first_user_message(self, session_id: str) -> str | None:
        """Get the first user message content for a session.

        Args:
            session_id: Session identifier

        Returns:
            First user message content, or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT content FROM conversations
                WHERE session_id = ? AND role = 'user'
                ORDER BY timestamp ASC LIMIT 1
                """,
                (session_id,)
            )
            row = cursor.fetchone()
            return row["content"] if row else None
        finally:
            conn.close()

    def get_all_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get all sessions with first message preview for sidebar display.

        Args:
            limit: Maximum number of sessions to retrieve

        Returns:
            List of session dictionaries with title, message_count,
            preview (first user message), timestamps
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT s.session_id, s.title, s.created_at, s.updated_at,
                       s.message_count,
                       (SELECT c.content FROM conversations c
                        WHERE c.session_id = s.session_id AND c.role = 'user'
                        ORDER BY c.timestamp ASC LIMIT 1) as first_message
                FROM sessions s
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "session_id": row["session_id"],
                    "title": row["title"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "message_count": row["message_count"],
                    "first_message": row["first_message"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_session_messages(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get all messages for a specific session.

        Args:
            session_id: Session identifier
            limit: Maximum number of messages

        Returns:
            List of message dictionaries
        """
        return self.get_history(session_id=session_id, limit=limit)
