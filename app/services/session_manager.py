"""
Session management service for agent conversations.

Manages session lifecycle:
- Create new sessions
- Track active sessions
- Clean up sessions and conversation history
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Set
from pathlib import Path
import os
import sqlite3

from app.services.agno_agent import AgnoAgentService

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages agent conversation sessions.
    
    Each session maintains:
    - Unique session ID
    - Agent service instance
    - Session creation timestamp
    - Last activity timestamp
    """
    
    def __init__(self, db_file: str = "tmp/agents.db"):
        """
        Initialize session manager.
        
        Args:
            db_file: Path to SQLite database file for chat history
        """
        self.db_file = db_file
        self.sessions: Dict[str, Dict] = {}  # session_id -> session_data
        self._ensure_db_directory()
    
    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        db_path = Path(self.db_file)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def create_session(self) -> str:
        """
        Create a new session and return session ID.
        
        Returns:
            Unique session ID (UUID string)
        """
        session_id = str(uuid.uuid4())
        
        # Initialize agent service for this session
        agent_service = AgnoAgentService(
            agent_name="Meeting Transcript Assistant",
            model_id="openai/gpt-oss-120b",
            enable_chat_history=True,
            num_history_runs=2  # Reduced from 5 to 2 - prevents context overflow
        )
        
        # Store session data
        self.sessions[session_id] = {
            "session_id": session_id,
            "agent_service": agent_service,
            "created_at": datetime.utcnow(),
            "last_activity": datetime.utcnow()
        }
        
        logger.info(f"Created new session: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[AgnoAgentService]:
        """
        Get agent service for a session.
        Updates last activity timestamp.
        
        Args:
            session_id: Session ID
            
        Returns:
            AgnoAgentService instance if session exists, None otherwise
        """
        if session_id not in self.sessions:
            logger.warning(f"Session not found: {session_id}")
            return None
        
        # Update last activity
        self.sessions[session_id]["last_activity"] = datetime.utcnow()
        return self.sessions[session_id]["agent_service"]
    
    def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if session exists, False otherwise
        """
        return session_id in self.sessions
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and clean up its conversation history.
        
        Args:
            session_id: Session ID to delete
            
        Returns:
            True if session was deleted, False if session didn't exist
        """
        if session_id not in self.sessions:
            logger.info(f"Session {session_id} not found (may have been already deleted)")
            return False
        
        # Clean up conversation history from database
        try:
            self._cleanup_session_history(session_id)
        except Exception as e:
            logger.error(f"Error cleaning up session history for {session_id}: {e}")
        
        # Remove session from memory
        del self.sessions[session_id]
        logger.info(f"Deleted session: {session_id}")
        return True
    
    def _cleanup_session_history(self, session_id: str):
        """
        Delete conversation history for a session from the database.
        
        Args:
            session_id: Session ID to clean up
        """
        if not os.path.exists(self.db_file):
            logger.debug(f"Database file does not exist: {self.db_file}")
            return
        
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            
            # Get all tables in the database
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            total_deleted = 0
            
            for table in tables:
                try:
                    # Get column names for this table
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = [row[1] for row in cursor.fetchall()]
                    
                    # Check if table has session_id column (case-insensitive)
                    session_id_column = None
                    for col in columns:
                        if col.lower() in ['session_id', 'sessionid', 'session']:
                            session_id_column = col
                            break
                    
                    if session_id_column:
                        # Delete rows for this session
                        cursor.execute(f"DELETE FROM {table} WHERE {session_id_column} = ?", (session_id,))
                        deleted = cursor.rowcount
                        if deleted > 0:
                            logger.info(f"Deleted {deleted} records from {table} for session {session_id}")
                            total_deleted += deleted
                    
                except sqlite3.Error as e:
                    logger.debug(f"Error processing table {table}: {e}")
                    continue
            
            conn.commit()
            conn.close()
            
            if total_deleted > 0:
                logger.info(f"Cleaned up {total_deleted} conversation history records for session: {session_id}")
            else:
                logger.debug(f"No conversation history found to clean up for session: {session_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning up session history: {e}")
            # Don't raise - session deletion should still succeed even if cleanup fails
    
    def cleanup_inactive_sessions(self, max_age_minutes: int = 60):
        """
        Clean up sessions that haven't been active for a while.
        Useful for periodic cleanup of abandoned sessions.
        
        Args:
            max_age_minutes: Maximum age in minutes before session is considered inactive
        """
        now = datetime.utcnow()
        inactive_sessions = []
        
        for session_id, session_data in self.sessions.items():
            last_activity = session_data["last_activity"]
            age_minutes = (now - last_activity).total_seconds() / 60
            
            if age_minutes > max_age_minutes:
                inactive_sessions.append(session_id)
        
        for session_id in inactive_sessions:
            logger.info(f"Cleaning up inactive session: {session_id}")
            self.delete_session(session_id)
        
        if inactive_sessions:
            logger.info(f"Cleaned up {len(inactive_sessions)} inactive sessions")
    
    def get_active_sessions_count(self) -> int:
        """
        Get count of active sessions.
        
        Returns:
            Number of active sessions
        """
        return len(self.sessions)

