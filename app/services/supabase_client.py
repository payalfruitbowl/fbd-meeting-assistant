"""
Supabase client service for database operations and authentication.
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from supabase import create_client, Client
from app.config import settings

logger = logging.getLogger(__name__)


class SupabaseClient:
    """
    Supabase client for managing database operations and authentication.
    """
    
    def __init__(self):
        """Initialize Supabase client."""
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            logger.warning("Supabase credentials not configured. Chat history features will be disabled.")
            self.client: Optional[Client] = None
            return
        
        try:
            self.client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            self.client = None
    
    def is_configured(self) -> bool:
        """Check if Supabase is configured."""
        return self.client is not None
    
    # Authentication methods
    def sign_up(self, email: str, password: str) -> Dict[str, Any]:
        """
        Sign up a new user.
        
        Args:
            email: User email
            password: User password
            
        Returns:
            User data and session
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            response = self.client.auth.sign_up({
                "email": email,
                "password": password
            })
            return {
                "user": response.user.model_dump() if response.user else None,
                "session": response.session.model_dump() if response.session else None
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error signing up user: {error_msg}")
            # Extract more specific error message if available
            if hasattr(e, 'message'):
                error_msg = e.message
            elif hasattr(e, 'args') and e.args:
                error_msg = str(e.args[0])
            raise ValueError(f"Sign up failed: {error_msg}")
    
    def sign_in(self, email: str, password: str) -> Dict[str, Any]:
        """
        Sign in a user.
        
        Args:
            email: User email
            password: User password
            
        Returns:
            User data and session
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            response = self.client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            return {
                "user": response.user.model_dump() if response.user else None,
                "session": response.session.model_dump() if response.session else None
            }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error signing in user: {error_msg}")
            # Extract more specific error message if available
            if hasattr(e, 'message'):
                error_msg = e.message
            elif hasattr(e, 'args') and e.args:
                error_msg = str(e.args[0])
            raise ValueError(f"Sign in failed: {error_msg}")
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify a JWT token and get user info.
        
        Args:
            token: JWT token
            
        Returns:
            User data if token is valid, None otherwise
        """
        if not self.client:
            return None
        
        try:
            # Set the session with the token
            self.client.auth.set_session(access_token=token, refresh_token="")
            user = self.client.auth.get_user(token)
            if user:
                return user.user.model_dump()
            return None
        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
            return None
    
    # Conversation methods
    def create_conversation(self, user_id: str, title: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new conversation.
        
        Args:
            user_id: User ID (from auth)
            title: Optional conversation title
            
        Returns:
            Created conversation data
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            conversation_data = {
                "user_id": user_id,
                "title": title or f"Conversation {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }
            
            result = self.client.table("conversations").insert(conversation_data).execute()
            if result.data:
                return result.data[0]
            raise Exception("Failed to create conversation")
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            raise
    
    def get_conversations(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get all conversations for a user.
        
        Args:
            user_id: User ID
            limit: Maximum number of conversations to return
            
        Returns:
            List of conversations
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            result = self.client.table("conversations")\
                .select("*")\
                .eq("user_id", user_id)\
                .order("updated_at", desc=True)\
                .limit(limit)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting conversations: {e}")
            raise
    
    def get_conversation(self, conversation_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific conversation by ID.
        
        Args:
            conversation_id: Conversation ID
            user_id: User ID (for security - ensure user owns this conversation)
            
        Returns:
            Conversation data or None
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            result = self.client.table("conversations")\
                .select("*")\
                .eq("id", conversation_id)\
                .eq("user_id", user_id)\
                .execute()
            
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Error getting conversation: {e}")
            raise
    
    def update_conversation_title(self, conversation_id: str, user_id: str, title: str) -> Dict[str, Any]:
        """
        Update conversation title.
        
        Args:
            conversation_id: Conversation ID
            user_id: User ID
            title: New title
            
        Returns:
            Updated conversation data
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            result = self.client.table("conversations")\
                .update({
                    "title": title,
                    "updated_at": datetime.utcnow().isoformat()
                })\
                .eq("id", conversation_id)\
                .eq("user_id", user_id)\
                .execute()
            
            if result.data:
                return result.data[0]
            raise Exception("Failed to update conversation")
        except Exception as e:
            logger.error(f"Error updating conversation: {e}")
            raise
    
    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """
        Delete a conversation and all its messages.
        
        Args:
            conversation_id: Conversation ID
            user_id: User ID
            
        Returns:
            True if deleted, False otherwise
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            # Delete messages first (if foreign key constraints require it)
            self.client.table("messages")\
                .delete()\
                .eq("conversation_id", conversation_id)\
                .execute()
            
            # Delete conversation
            result = self.client.table("conversations")\
                .delete()\
                .eq("id", conversation_id)\
                .eq("user_id", user_id)\
                .execute()
            
            return len(result.data) > 0 if result.data else False
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            raise
    
    # Message methods
    def add_message(self, conversation_id: str, role: str, content: str) -> Dict[str, Any]:
        """
        Add a message to a conversation.
        
        Args:
            conversation_id: Conversation ID
            role: Message role ('user' or 'assistant')
            content: Message content
            
        Returns:
            Created message data
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            message_data = {
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": datetime.utcnow().isoformat()
            }
            
            result = self.client.table("messages").insert(message_data).execute()
            if result.data:
                # Update conversation updated_at
                self.client.table("conversations")\
                    .update({"updated_at": datetime.utcnow().isoformat()})\
                    .eq("id", conversation_id)\
                    .execute()
                
                return result.data[0]
            raise Exception("Failed to create message")
        except Exception as e:
            logger.error(f"Error adding message: {e}")
            raise
    
    def get_messages(self, conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get all messages for a conversation.
        
        Args:
            conversation_id: Conversation ID
            limit: Maximum number of messages to return
            
        Returns:
            List of messages
        """
        if not self.client:
            raise ValueError("Supabase not configured")
        
        try:
            result = self.client.table("messages")\
                .select("*")\
                .eq("conversation_id", conversation_id)\
                .order("created_at", desc=False)\
                .limit(limit)\
                .execute()
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            raise

