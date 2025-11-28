"""
Main FastAPI application entry point.
Fireflies transcript processor and AI chat assistant.
"""
from fastapi import FastAPI, HTTPException, Depends
from starlette.responses import StreamingResponse
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import logging
import json
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

# Import Fireflies services
from app.config import settings
from app.services.fireflies_client import FirefliesClient
from app.services.data_processor import DataProcessor
from app.services.word_generator import WordGenerator
from app.services.session_manager import SessionManager
from app.services.supabase_client import SupabaseClient
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create main app
app = FastAPI(
    title="Fruitbowl Assistant",
    description="AI chat assistant with Fireflies transcript processing",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize session manager (singleton)
# No longer needs SQLite database - chat history handled by Supabase
session_manager = SessionManager()

# Initialize Supabase client (singleton)
supabase_client = SupabaseClient()

# Security scheme for JWT tokens
security = HTTPBearer()

# Fireflies Pydantic models
class ClientTranscriptsRequest(BaseModel):
    client: str = Field(..., description="Client domain or brand label (e.g., 'everme.ai' or 'Croffle Guys')")
    start_date: datetime = Field(..., description="Start of period (ISO 8601)")
    end_date: datetime = Field(..., description="End of period (ISO 8601)")
    use_llm: Optional[bool] = True

class ClientTranscriptsResponse(BaseModel):
    status: str
    client: str
    period: Dict[str, str]
    files_generated: int
    file_path: Optional[str] = None
    total_meetings_included: int = 0

class AgentQueryRequest(BaseModel):
    question: str = Field(..., description="User question to ask the agent")
    session_id: Optional[str] = Field(None, description="Session ID for conversation continuity. If not provided, a new session will be created.")
    conversation_id: Optional[str] = Field(None, description="Supabase conversation ID to save messages to. If provided, messages will be saved to chat history.")

class AgentQueryResponse(BaseModel):
    status: str
    response: str
    session_id: str
    message: Optional[str] = None

class SessionCreateResponse(BaseModel):
    status: str
    session_id: str
    message: str


# Authentication models
class SignUpRequest(BaseModel):
    email: str = Field(..., description="User email")
    password: str = Field(..., min_length=6, description="User password (min 6 characters)")


class SignInRequest(BaseModel):
    email: str = Field(..., description="User email")
    password: str = Field(..., description="User password")


class AuthResponse(BaseModel):
    status: str
    user: Optional[Dict[str, Any]] = None
    session: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


# Conversation models
class ConversationResponse(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class CreateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, description="Conversation title")


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str


class AddMessageRequest(BaseModel):
    conversation_id: str = Field(..., description="Conversation ID")
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class UpdateConversationTitleRequest(BaseModel):
    title: str = Field(..., description="New conversation title")

# Fireflies routes
@app.get("/")
async def root():
    """Root endpoint."""
    return {"status": "ok", "message": "Fruitbowl Assistant API"}

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/test-api")
async def test_api():
    """Debug endpoint to test Fireflies API."""
    try:
        logger.info("Testing Fireflies API connection")
        fireflies_client = FirefliesClient()
        transcripts = await fireflies_client.get_weekly_transcripts()
        
        return {
            "status": "success",
            "total_transcripts": len(transcripts),
            "sample_transcript": transcripts[0] if transcripts else None,
            "all_transcripts": transcripts,
            "message": "Check the response structure to update data processing logic"
        }
    except Exception as e:
        logger.error(f"Error testing API: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "message": "This helps us understand the correct API endpoint and parameters"
        }

@app.post("/process-transcripts")
async def process_transcripts():
    """Main endpoint to process Fireflies transcripts for the past week."""
    try:
        logger.info("Starting transcript processing for past week")
        
        fireflies_client = FirefliesClient()
        data_processor = DataProcessor()
        word_generator = WordGenerator()
        
        logger.info("Fetching transcripts from Fireflies API")
        transcripts = await fireflies_client.get_weekly_transcripts()
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        date_range_str = f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
        logger.info(f"Calculated date range for Flow 1: {date_range_str}")
        
        if not transcripts:
            logger.warning("No transcripts found for the past week")
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "No transcripts found for the past week",
                    "files_generated": 0
                }
            )
        
        logger.info("Processing and filtering transcripts")
        client_transcripts = await data_processor.filter_by_clients_async(transcripts)
        
        logger.info(f"Generating Word documents for {len(client_transcripts)} clients")
        generated_files = []
        
        for client_name, conversations in client_transcripts.items():
            formatted_text = data_processor.format_conversations(conversations)
            logger.info(f"Generating Word doc for {client_name} with date_range={date_range_str}")
            file_path = await word_generator.create_document(client_name, formatted_text, date_range=date_range_str)
            generated_files.append({
                "client": client_name,
                "file_path": file_path
            })
        
        logger.info(f"Successfully generated {len(generated_files)} Word documents")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"Processed {len(client_transcripts)} clients",
                "files_generated": len(generated_files),
                "files": generated_files
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing transcripts: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing transcripts: {str(e)}"
        )

@app.post("/process-transcripts-client", response_model=ClientTranscriptsResponse)
async def process_transcripts_client(req: ClientTranscriptsRequest):
    """Process transcripts for a specific client within a date range."""
    try:
        logger.info(f"Processing client '{req.client}' from {req.start_date} to {req.end_date} (use_llm={req.use_llm})")
        fireflies_client = FirefliesClient()
        data_processor = DataProcessor()
        word_generator = WordGenerator()

        from_date_str = req.start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to_date_str = req.end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        transcripts = await fireflies_client.get_transcripts_list_between(from_date_str, to_date_str)
        if not transcripts:
            return ClientTranscriptsResponse(
                status="success",
                client=req.client,
                period={"from": from_date_str, "to": to_date_str},
                files_generated=0,
                file_path=None,
                total_meetings_included=0,
            )

        filtered = await data_processor.filter_for_client_async(
            transcripts=transcripts,
            client_query=req.client,
            use_llm=False,
        )

        if not filtered:
            return ClientTranscriptsResponse(
                status="success",
                client=req.client,
                period={"from": from_date_str, "to": to_date_str},
                files_generated=0,
                file_path=None,
                total_meetings_included=0,
            )

        logger.info(f"Fetching full transcript details for {len(filtered)} filtered transcripts")
        full_transcripts = []
        for transcript_info in filtered:
            transcript_id = transcript_info.get("id")
            if transcript_id:
                try:
                    full_transcript = await fireflies_client.get_transcript_details(transcript_id)
                    full_transcript.update(transcript_info)
                    full_transcripts.append(full_transcript)
                except Exception as e:
                    logger.warning(f"Failed to fetch full transcript {transcript_id}: {str(e)}")
                    full_transcripts.append(transcript_info)

        date_range_str = f"{req.start_date.strftime('%B %d')} - {req.end_date.strftime('%B %d, %Y')}"
        
        formatted_text = data_processor.format_conversations(full_transcripts)
        file_path = await word_generator.create_document(req.client, formatted_text, output_subdir="output-2", date_range=date_range_str)

        return ClientTranscriptsResponse(
            status="success",
            client=req.client,
            period={"from": from_date_str, "to": to_date_str},
            files_generated=1,
            file_path=file_path,
            total_meetings_included=len(filtered),
        )
    except Exception as e:
        logger.error(f"Error in process-transcripts-client: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/agent/query/stream")
async def agent_query_stream(req: AgentQueryRequest):
    """
    Stream query the agent with a question (Server-Sent Events).

    This endpoint:
    - Creates a new session if session_id is not provided
    - Uses existing session if session_id is provided (maintains conversation history)
    - Streams response chunks as they are generated
    - Automatically ensures metadata filters are registered before querying

    Args:
        req: AgentQueryRequest with question and optional session_id

    Returns:
        StreamingResponse with SSE format:
        - data: {"type": "session", "session_id": "..."}
        - data: {"type": "chunk", "content": "..."}
        - data: {"type": "done", "response": "...", "session_id": "..."}
    """
    async def generate():
        try:
            # Get or create session
            if req.session_id:
                # Use existing session
                if not session_manager.session_exists(req.session_id):
                    logger.warning(f"Session not found: {req.session_id}, creating new session")
                    session_id = session_manager.create_session()
                else:
                    session_id = req.session_id
            else:
                # Create new session
                session_id = session_manager.create_session()

            # Get agent service for this session
            agent_service = session_manager.get_session(session_id)
            if not agent_service:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Failed to get agent service for session'})}\n\n"
                return

            # Send session ID first
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            # Note: User message will be saved AFTER processing to avoid confusion in history loading

            # Query the agent with streaming (this ensures metadata is registered)
            logger.info(f"Streaming query to agent (session: {session_id}): {req.question[:100]}...")
            full_response = ""

            async for chunk in agent_service.astream_query(req.question, session_id=session_id, conversation_id=req.conversation_id):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            # Save both user message and assistant response to Supabase
            if req.conversation_id and supabase_client.is_configured():
                try:
                    # Save user message and assistant response
                    supabase_client.add_message(req.conversation_id, "user", req.question)
                    supabase_client.add_message(req.conversation_id, "assistant", full_response)
                    logger.info(f"Saved conversation messages to {req.conversation_id}")
                except Exception as e:
                    logger.warning(f"Failed to save messages to Supabase: {e}")
                    # Don't fail the request if saving fails

            # Send completion message
            yield f"data: {json.dumps({'type': 'done', 'response': full_response, 'session_id': session_id})}\n\n"

        except Exception as e:
            logger.error(f"Error in streaming agent query: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@app.post("/agent/query", response_model=AgentQueryResponse)
async def agent_query(req: AgentQueryRequest):
    """Query the agent with a question."""
    try:
        if req.session_id:
            if not session_manager.session_exists(req.session_id):
                logger.warning(f"Session not found: {req.session_id}, creating new session")
                session_id = session_manager.create_session()
            else:
                session_id = req.session_id
        else:
            session_id = session_manager.create_session()
        
        agent_service = session_manager.get_session(session_id)
        if not agent_service:
            raise HTTPException(status_code=500, detail="Failed to get agent service for session")
        
        logger.info(f"Querying agent (session: {session_id}): {req.question[:100]}...")
        response = agent_service.query(req.question, session_id=session_id)
        
        return AgentQueryResponse(
            status="success",
            response=response,
            session_id=session_id,
            message="Query processed successfully"
        )
        
    except Exception as e:
        logger.error(f"Error in agent query: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

@app.post("/agent/session/create", response_model=SessionCreateResponse)
async def create_session():
    """Create a new agent session."""
    try:
        session_id = session_manager.create_session()
        return SessionCreateResponse(
            status="success",
            session_id=session_id,
            message="Session created successfully"
        )
    except Exception as e:
        logger.error(f"Error creating session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating session: {str(e)}")

@app.delete("/agent/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and clean up its conversation history."""
    try:
        deleted = session_manager.delete_session(session_id)
        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"Session {session_id} {'deleted successfully' if deleted else 'already deleted or not found'}",
                "session_id": session_id
            }
        )
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")

@app.get("/agent/sessions/count")
async def get_sessions_count():
    """Get count of active sessions."""
    try:
        count = session_manager.get_active_sessions_count()
        return {
            "status": "success",
            "active_sessions": count
        }
    except Exception as e:
        logger.error(f"Error getting sessions count: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting sessions count: {str(e)}")


# Helper functions for authentication
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    """
    Get current user from JWT token.

    Args:
        credentials: HTTP Bearer token credentials

    Returns:
        User data

    Raises:
        HTTPException: If token is invalid or user not found
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Authentication service not configured")

    token = credentials.credentials
    user = supabase_client.verify_token(token)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user


# ============================================================================
# Authentication Endpoints
# ============================================================================

@app.post("/auth/signup", response_model=AuthResponse)
async def sign_up(request: SignUpRequest):
    """
    Sign up a new user.

    Args:
        request: Sign up request with email and password

    Returns:
        User data and session token
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Authentication service not configured")

    try:
        result = supabase_client.sign_up(request.email, request.password)
        return AuthResponse(
            status="success",
            user=result.get("user"),
            session=result.get("session"),
            message="User created successfully"
        )
    except Exception as e:
        logger.error(f"Sign up error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/signin", response_model=AuthResponse)
async def sign_in(request: SignInRequest):
    """
    Sign in a user.

    Args:
        request: Sign in request with email and password

    Returns:
        User data and session token
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Authentication service not configured")

    try:
        result = supabase_client.sign_in(request.email, request.password)
        return AuthResponse(
            status="success",
            user=result.get("user"),
            session=result.get("session"),
            message="Signed in successfully"
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Sign in error: {error_msg}", exc_info=True)
        # Provide more specific error message
        if "Invalid login credentials" in error_msg or "Email not confirmed" in error_msg:
            raise HTTPException(status_code=401, detail=error_msg)
        raise HTTPException(status_code=401, detail=f"Sign in failed: {error_msg}")


@app.get("/auth/me")
async def get_current_user_info(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get current user information.

    Args:
        current_user: Current user (from token)

    Returns:
        User data
    """
    return {
        "status": "success",
        "user": current_user
    }


# ============================================================================
# Conversation Endpoints
# ============================================================================

@app.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: CreateConversationRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Create a new conversation.

    Args:
        request: Conversation creation request
        current_user: Current user (from token)

    Returns:
        Created conversation
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        conversation = supabase_client.create_conversation(user_id, request.title)
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations", response_model=List[ConversationResponse])
async def get_conversations(
    limit: int = 50,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all conversations for the current user.

    Args:
        limit: Maximum number of conversations to return
        current_user: Current user (from token)

    Returns:
        List of conversations
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        conversations = supabase_client.get_conversations(user_id, limit)
        return [ConversationResponse(**conv) for conv in conversations]
    except Exception as e:
        logger.error(f"Error getting conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get a specific conversation by ID.

    Args:
        conversation_id: Conversation ID
        current_user: Current user (from token)

    Returns:
        Conversation data
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        conversation = supabase_client.get_conversation(conversation_id, user_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return ConversationResponse(**conversation)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/conversations/{conversation_id}")
async def update_conversation_title(
    conversation_id: str,
    request: UpdateConversationTitleRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Update conversation title.

    Args:
        conversation_id: Conversation ID
        request: Update request with new title
        current_user: Current user (from token)

    Returns:
        Updated conversation
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        conversation = supabase_client.update_conversation_title(conversation_id, user_id, request.title)
        return ConversationResponse(**conversation)
    except Exception as e:
        logger.error(f"Error updating conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Delete a conversation and all its messages.

    Args:
        conversation_id: Conversation ID
        current_user: Current user (from token)

    Returns:
        Success status
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        deleted = supabase_client.delete_conversation(conversation_id, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")

        return {"status": "success", "message": "Conversation deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Message Endpoints
# ============================================================================

@app.post("/messages", response_model=MessageResponse)
async def add_message(
    request: AddMessageRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Add a message to a conversation.

    Args:
        request: Message creation request
        current_user: Current user (from token)

    Returns:
        Created message
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        # Verify user owns the conversation
        conversation = supabase_client.get_conversation(request.conversation_id, user_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if request.role not in ["user", "assistant"]:
            raise HTTPException(status_code=400, detail="Role must be 'user' or 'assistant'")

        message = supabase_client.add_message(
            request.conversation_id,
            request.role,
            request.content
        )
        return MessageResponse(**message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding message: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: str,
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all messages for a conversation.

    Args:
        conversation_id: Conversation ID
        limit: Maximum number of messages to return
        current_user: Current user (from token)

    Returns:
        List of messages
    """
    if not supabase_client.is_configured():
        raise HTTPException(status_code=503, detail="Database service not configured")

    try:
        user_id = current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Invalid user data")

        # Verify user owns the conversation
        conversation = supabase_client.get_conversation(conversation_id, user_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

        messages = supabase_client.get_messages(conversation_id, limit)
        return [MessageResponse(**msg) for msg in messages]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

