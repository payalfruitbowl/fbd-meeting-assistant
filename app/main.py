"""
FastAPI main application entry point.
"""
from fastapi import FastAPI, HTTPException
from starlette.requests import Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import json
from datetime import datetime, timedelta
import logging
from pydantic import BaseModel, Field
from typing import Optional, Dict

from app.config import settings
from app.services.fireflies_client import FirefliesClient
from app.services.data_processor import DataProcessor
from app.services.word_generator import WordGenerator
from app.services.session_manager import SessionManager

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


class AgentQueryResponse(BaseModel):
    status: str
    response: str
    session_id: str
    message: Optional[str] = None


class SessionCreateResponse(BaseModel):
    status: str
    session_id: str
    message: str

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
