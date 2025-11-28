"""
FastAPI main application entry point.
"""
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from starlette.requests import Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import json
from datetime import datetime, timedelta
import logging
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any

from app.config import settings
from app.services.fireflies_client import FirefliesClient
from app.services.data_processor import DataProcessor
from app.services.word_generator import WordGenerator
from app.services.session_manager import SessionManager
from app.services.pinecone_client import PineconeClient
from app.services.transcript_cleaner import TranscriptCleaner
from app.services.supabase_client import SupabaseClient
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Fireflies Transcript Processor",
    description="API to fetch, process, and generate Word documents from Fireflies transcripts",
    version="1.0.0"
)

# Add CORS middleware
# Parse allowed origins from environment variable (comma-separated)
allowed_origins = [origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

# Log allowed origins for debugging
logger.info(f"CORS allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Frontend URLs from environment
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],  # Explicit methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"],  # Expose all headers
)

# Initialize session manager (singleton)
session_manager = SessionManager()

# Initialize Supabase client (singleton)
supabase_client = SupabaseClient()

# Security scheme for JWT tokens
security = HTTPBearer()

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

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "Fireflies Transcript Processor API"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.options("/{full_path:path}")
async def options_handler(full_path: str, request: Request):
    """Handle OPTIONS requests for CORS preflight."""
    origin = request.headers.get("origin")
    
    # Check if origin is in allowed origins
    if origin and origin in allowed_origins:
        return JSONResponse(
            content={},
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "3600",
            }
        )
    else:
        # Return 200 even if origin not in list (let middleware handle it)
        return JSONResponse(content={})


@app.get("/test-api")
async def test_api():
    """
    Debug endpoint to test Fireflies API and see the raw response structure.
    Use this to understand the API response format.
    """
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
    """
    Main endpoint to process Fireflies transcripts for the past week.
    Called by n8n weekly trigger.
    
    Returns:
        JSON response with processing status and file locations
    """
    try:
        logger.info("Starting transcript processing for past week")
        
        # Initialize services
        fireflies_client = FirefliesClient()
        data_processor = DataProcessor()
        word_generator = WordGenerator()
        
        # Fetch transcripts from Fireflies API
        logger.info("Fetching transcripts from Fireflies API")
        transcripts = await fireflies_client.get_weekly_transcripts()
        
        # Calculate date range for past week
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
        
        # Process and filter transcripts by unique clients
        logger.info("Processing and filtering transcripts")
        client_transcripts = await data_processor.filter_by_clients_async(transcripts)
        
        # Generate Word documents for each client
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
    """
    Process transcripts for a specific client within a date range.
    Supports domain-based or brand-label client matching.
    """
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

        # Flow 2: Direct search only (no LLM - if not in title/domains, LLM won't find it either)
        filtered = await data_processor.filter_for_client_async(
            transcripts=transcripts,
            client_query=req.client,
            use_llm=False,  # Disabled: direct search is sufficient
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

        # Fetch full transcript details (sentences) for filtered transcripts
        logger.info(f"Fetching full transcript details for {len(filtered)} filtered transcripts")
        full_transcripts = []
        for transcript_info in filtered:
            transcript_id = transcript_info.get("id")
            if transcript_id:
                try:
                    full_transcript = await fireflies_client.get_transcript_details(transcript_id)
                    # Merge basic info with full details
                    full_transcript.update(transcript_info)
                    full_transcripts.append(full_transcript)
                except Exception as e:
                    logger.warning(f"Failed to fetch full transcript {transcript_id}: {str(e)}")
                    # Use basic info if full fetch fails
                    full_transcripts.append(transcript_info)

        # Format date range for display
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
            
            # Query the agent with streaming (this ensures metadata is registered)
            logger.info(f"Streaming query to agent (session: {session_id}): {req.question[:100]}...")
            full_response = ""
            
            async for chunk in agent_service.astream_query(req.question, session_id=session_id):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"
            
            # Save messages to Supabase if conversation_id is provided
            if req.conversation_id and supabase_client.is_configured():
                try:
                    # Save user message
                    supabase_client.add_message(req.conversation_id, "user", req.question)
                    # Save assistant response
                    supabase_client.add_message(req.conversation_id, "assistant", full_response)
                    logger.info(f"Saved messages to conversation {req.conversation_id}")
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
    """
    Query the agent with a question (non-streaming, returns full response).
    
    This endpoint:
    - Creates a new session if session_id is not provided
    - Uses existing session if session_id is provided (maintains conversation history)
    - Returns complete agent response and session_id
    - Automatically ensures metadata filters are registered before querying
    
    Args:
        req: AgentQueryRequest with question and optional session_id
        
    Returns:
        AgentQueryResponse with agent response and session_id
    """
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
            raise HTTPException(status_code=500, detail="Failed to get agent service for session")
        
        # Query the agent (use async method to ensure metadata registration)
        logger.info(f"Querying agent (session: {session_id}): {req.question[:100]}...")
        response = await agent_service.aquery(req.question, session_id=session_id)
        
        # Save messages to Supabase if conversation_id is provided
        if req.conversation_id and supabase_client.is_configured():
            try:
                # Save user message
                supabase_client.add_message(req.conversation_id, "user", req.question)
                # Save assistant response
                supabase_client.add_message(req.conversation_id, "assistant", response)
                logger.info(f"Saved messages to conversation {req.conversation_id}")
            except Exception as e:
                logger.warning(f"Failed to save messages to Supabase: {e}")
                # Don't fail the request if saving fails
        
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
    """
    Create a new agent session.
    
    Returns:
        SessionCreateResponse with new session_id
    """
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
    """
    Delete a session and clean up its conversation history.
    
    This should be called when:
    - User closes the tab/window
    - User explicitly ends the session
    - Session cleanup is needed
    
    Args:
        session_id: Session ID to delete
        
    Returns:
        JSON response with deletion status
    """
    try:
        deleted = session_manager.delete_session(session_id)
        # Return success even if session didn't exist (idempotent operation)
        # The goal is achieved: session is gone
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
    """
    Get count of active sessions.
    
    Returns:
        JSON response with active session count
    """
    try:
        count = session_manager.get_active_sessions_count()
        return {
            "status": "success",
            "active_sessions": count
        }
    except Exception as e:
        logger.error(f"Error getting sessions count: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting sessions count: {str(e)}")


# Helper functions for daily sync (reused from backfill_transcripts.py)
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split text into fixed-size chunks with overlap."""
    if not text:
        return []
    
    if len(text) <= chunk_size:
        return [text]
    
    if overlap >= chunk_size:
        overlap = chunk_size // 4
    
    chunks = []
    start = 0
    step = chunk_size - overlap
    
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += step
        if start >= len(text):
            break
    
    return chunks


def extract_transcript_text(transcript: Dict[str, Any], clean: bool = True) -> str:
    """Extract formatted text from transcript sentences."""
    if clean:
        transcript = TranscriptCleaner.clean_transcript(transcript)
        return TranscriptCleaner.format_cleaned_transcript_text(transcript)
    
    if "sentences" in transcript and transcript["sentences"]:
        lines = []
        for sentence in transcript["sentences"]:
            speaker = sentence.get("speaker_name", "Unknown Speaker")
            text = sentence.get("text", sentence.get("raw_text", ""))
            if text.strip():
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines)
    return ""


def identify_clients(transcript: Dict[str, Any], data_processor: DataProcessor) -> List[str]:
    """Identify ALL clients from transcript by extracting external domains from participant emails."""
    clients = []
    
    generic_providers = {
        "gmail.com", "outlook.com", "yahoo.com", "hotmail.com", 
        "icloud.com", "aol.com", "protonmail.com", "mail.com",
        "live.com", "msn.com", "ymail.com"
    }
    
    # Step 1: Try to extract client from title first
    title = transcript.get("title", "")
    if title and not title.lower().startswith("untitled"):
        brand = data_processor._brand_from_title(title)
        if brand:
            brand_normalized = brand.strip().replace(" ", "").replace("-", "")
            if brand_normalized:
                clients.append(brand_normalized)
    
    # Step 2: Extract ALL external domains from participant emails
    participants = transcript.get("participants", [])
    meeting_attendees = transcript.get("meeting_attendees", [])
    
    all_emails = set()
    if isinstance(participants, list):
        for participant in participants:
            if isinstance(participant, str):
                all_emails.add(participant.lower())
            elif isinstance(participant, dict):
                email = participant.get("email", "")
                if email:
                    all_emails.add(email.lower())
    
    if meeting_attendees:
        for attendee in meeting_attendees:
            if isinstance(attendee, dict):
                email = attendee.get("email", "")
                if email:
                    all_emails.add(email.lower())
    
    external_domains = set()
    for email in all_emails:
        if "@" in email:
            domain = email.split("@")[1].lower()
            if data_processor._is_internal_team(email):
                continue
            if domain in generic_providers:
                continue
            external_domains.add(domain)
    
    for domain in external_domains:
        domain_parts = domain.split(".")
        if domain_parts:
            domain_name = domain_parts[0]
            client_name = domain_name.title()
            if client_name not in clients:
                clients.append(client_name)
    
    return clients


async def run_daily_sync_background():
    """
    Background task that runs the actual daily sync.
    This runs independently of the HTTP request, so no timeouts!
    """
    try:
        logger.info("=" * 60)
        logger.info("Starting daily sync (background)")
        logger.info("=" * 60)
        
        # Initialize services
        fireflies_client = FirefliesClient()
        pinecone_client = PineconeClient()
        data_processor = DataProcessor()
        
        # Ensure index exists
        if not pinecone_client.index:
            if pinecone_client.index_name:
                try:
                    existing_indexes = pinecone_client.list_indexes()
                    if pinecone_client.index_name not in existing_indexes:
                        logger.info(f"Index '{pinecone_client.index_name}' does not exist. Creating...")
                        pinecone_client.create_index()
                    else:
                        pinecone_client.index = pinecone_client.pc.Index(pinecone_client.index_name)
                except Exception as e:
                    logger.error(f"Error ensuring index exists: {e}")
                    return
            else:
                logger.error("PINECONE_INDEX_NAME not configured")
                return
        
        # 1. Fetch last 1 day's transcripts
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=1)
        from_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        to_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        logger.info(f"Fetching transcripts from {start_date.date()} to {end_date.date()}")
        transcript_list = await fireflies_client.get_transcripts_list_between(
            from_date_str,
            to_date_str,
            limit=50
        )
        
        transcripts_processed = 0
        chunks_created = 0
        
        if transcript_list:
            logger.info(f"Found {len(transcript_list)} transcripts to process")
            
            # Fetch full transcript details
            full_transcripts = []
            for transcript_info in transcript_list:
                transcript_id = transcript_info.get("id")
                if transcript_id:
                    try:
                        full_transcript = await fireflies_client.get_transcript_details(transcript_id)
                        full_transcript.update(transcript_info)
                        full_transcripts.append(full_transcript)
                    except Exception as e:
                        logger.warning(f"Failed to fetch transcript {transcript_id}: {e}")
                        full_transcripts.append(transcript_info)
            
            # Process and store transcripts
            all_records = []
            
            for transcript in full_transcripts:
                transcript_id = transcript.get("id")
                if not transcript_id:
                    continue
                
                # Extract text (with cleaning)
                transcript_text = extract_transcript_text(transcript, clean=True)
                if not transcript_text.strip():
                    logger.warning(f"Skipping transcript {transcript_id}: No text content")
                    continue
                
                # Chunk the text
                chunk_size = 2500
                overlap = 200
                chunks = chunk_text(transcript_text, chunk_size=chunk_size, overlap=overlap)
                logger.info(f"  Transcript {transcript_id}: {len(chunks)} chunks")
                
                # Identify clients
                clients = identify_clients(transcript, data_processor)
                if clients:
                    logger.info(f"  Identified clients: {', '.join(clients)}")
                
                # Extract date and create numeric timestamp for filtering
                date_str = transcript.get("dateString") or transcript.get("date", "")
                date_timestamp = None  # Unix timestamp for numeric filtering
                
                if isinstance(date_str, str) and "T" in date_str:
                    # Extract date part only (YYYY-MM-DD)
                    date_str = date_str.split("T")[0]
                    # Create timestamp for numeric filtering (Pinecone requires numbers for $lt/$gt)
                    try:
                        from datetime import datetime as dt
                        date_obj = dt.strptime(date_str, "%Y-%m-%d")
                        date_timestamp = int(date_obj.timestamp())
                    except Exception as e:
                        logger.warning(f"Failed to parse date {date_str}: {e}")
                elif date_str:
                    # Try to parse if it's already in YYYY-MM-DD format
                    try:
                        from datetime import datetime as dt
                        date_obj = dt.strptime(date_str, "%Y-%m-%d")
                        date_timestamp = int(date_obj.timestamp())
                    except:
                        pass
                
                # Get title and participants
                title = transcript.get("title", "Untitled Meeting")
                participants = transcript.get("participants", [])
                if not participants and transcript.get("meeting_attendees"):
                    participants = [
                        attendee.get("email") 
                        for attendee in transcript.get("meeting_attendees", [])
                        if attendee.get("email")
                    ]
                
                # Create records for each chunk
                for i, chunk_text_content in enumerate(chunks):
                    record_id = f"meeting_{transcript_id}#chunk_{i}"
                    
                    record = {
                        "id": record_id,
                        "text": chunk_text_content,
                        "metadata": {
                            "meeting_id": transcript_id,
                            "date": date_str,
                            "date_timestamp": date_timestamp,
                            "client": clients,
                            "title": title,
                            "participants": participants,
                            "chunk_index": i,
                            "total_chunks": len(chunks),
                            "content": chunk_text_content,
                            "chunk_text": chunk_text_content[:200]
                        }
                    }
                    all_records.append(record)
                    chunks_created += 1
            
            # Upsert records in batches
            if all_records:
                logger.info(f"Upserting {len(all_records)} records to Pinecone...")
                batch_size = 50
                
                for i in range(0, len(all_records), batch_size):
                    batch = all_records[i:i + batch_size]
                    try:
                        pinecone_client.upsert_texts(batch)
                        logger.info(f"  ✓ Upserted batch {i//batch_size + 1} ({len(batch)} records)")
                    except Exception as e:
                        logger.error(f"  ✗ Failed to upsert batch {i//batch_size + 1}: {e}")
                
                transcripts_processed = len(full_transcripts)
                logger.info(f"✓ Successfully stored {chunks_created} chunks from {transcripts_processed} transcripts")
        else:
            logger.info("No new transcripts found for the past day")
        
        # 3. Clean old data (1 year back) - DISABLED TO PREVENT ACCIDENTAL DELETION
        # TODO: Re-enable with proper date range configuration if needed
        # logger.info("\nCleaning old data (older than 1 year)...")
        # cutoff_date = end_date - timedelta(days=365)
        # cutoff_timestamp = int(cutoff_date.timestamp())
        # 
        # try:
        #     # Delete vectors with date_timestamp less than cutoff
        #     # Pinecone filter format for numeric comparison
        #     filter_dict = {
        #         "date_timestamp": {"$lt": cutoff_timestamp}
        #     }
        #     pinecone_client.delete_by_filter(filter_dict)
        #     logger.info(f"✓ Cleaned data older than {cutoff_date.date()}")
        # except Exception as e:
        #     logger.warning(f"Failed to clean old data: {e}")
        #     # Don't fail the whole sync if cleanup fails
        
        logger.info("=" * 60)
        logger.info("Daily sync completed (background)")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error in background daily sync: {str(e)}", exc_info=True)


@app.post("/sync/daily")
async def sync_daily(background_tasks: BackgroundTasks):
    """
    Daily sync endpoint for n8n scheduled trigger.
    
    Returns immediately (202 Accepted) and processes sync in background.
    This prevents timeouts - the sync can take as long as needed!
    
    Returns:
        JSON response with status "accepted" - processing continues in background
    """
    # Add background task - this will run independently of the HTTP request
    background_tasks.add_task(run_daily_sync_background)
    
    logger.info("Daily sync request received - processing in background")
    
    return JSONResponse(
        status_code=202,  # 202 Accepted - processing in background
        content={
            "status": "accepted",
            "message": "Daily sync started in background",
            "note": "Processing will continue even if this request completes. Check logs for progress."
        }
    )


# ============================================================================
# Authentication Endpoints
# ============================================================================

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
