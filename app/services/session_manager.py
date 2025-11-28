"""
Session management service for agent conversations.

Manages session lifecycle:
- Create new sessions
- Track active sessions
- Clean up sessions (conversation history handled by Supabase)
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Set

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
    
    def __init__(self):
        """
        Initialize session manager.
        Chat history is now handled by Supabase, so no SQLite database needed.
        """
        self.sessions: Dict[str, Dict] = {}  # session_id -> session_data
    
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
        Delete a session.
        Note: Conversation history is now handled by Supabase and cleaned up via API calls.

        Args:
            session_id: Session ID to delete

        Returns:
            True if session was deleted, False if session didn't exist
        """
        if session_id not in self.sessions:
            logger.info(f"Session {session_id} not found (may have been already deleted)")
            return False

        # Remove session from memory
        # Conversation history cleanup is handled by Supabase via API calls
        del self.sessions[session_id]
        logger.info(f"Deleted session: {session_id}")
        return True
    
    
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

