"""
Agno agent service for connecting to existing Pinecone index.

This service creates an Agno agent that uses:
- Existing Pinecone index (created separately via PineconeClient or CLI)
- FastEmbed for local embeddings (no API calls)
- Knowledge base for RAG functionality
- Groq for LLM inference

Note: This service only connects to existing indexes. Index management
(create/delete/upsert) is handled separately by PineconeClient.
"""
import logging
import os
import asyncio
from pathlib import Path
from typing import Optional
from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pineconedb import PineconeDb
from agno.knowledge.embedder.fastembed import FastEmbedEmbedder
from agno.models.groq import Groq
# from agno.db.postgres import PostgresDb  # Removed - using Supabase REST API instead

from app.config import settings
from app.services.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


class AgnoAgentService:
    """
    Agno agent service that connects to existing Pinecone index.
    Uses FastEmbed for local embeddings.
    """
    
    def __init__(
        self,
        index_name: Optional[str] = None,
        agent_name: str = "Knowledge Assistant",
        model_id: str = "openai/gpt-oss-120b",  # Default Groq model ID
        temperature: float = 0,
        top_p: float = 1,
        search_knowledge: bool = True,
        enable_chat_history: bool = True,
        num_history_runs: int = 3,  # Reduced from 5 to 3 - prevents context overflow while maintaining conversation continuity
        conversation_id: Optional[str] = None  # For saving messages to Supabase
    ):
        """
        Initialize Agno agent with Pinecone knowledge base.
        
        Args:
            index_name: Name of existing Pinecone index (uses config default if not provided)
            agent_name: Name of the agent
            model_id: Groq model ID (e.g., "openai/gpt-oss-120b", "llama-3.1-70b-versatile")
            temperature: Model temperature (default: 0 for deterministic)
            top_p: Model top_p parameter (default: 1)
            search_knowledge: Enable automatic knowledge base search
            enable_chat_history: Enable session-level chat history (requires database)
            num_history_runs: Number of previous messages to include in context (default: 2, reduced to prevent context overflow)
        """
        if not settings.PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY must be set in environment variables")
        
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY must be set in environment variables")
        
        name = index_name or settings.PINECONE_INDEX_NAME
        if not name:
            raise ValueError("Index name must be provided or set in PINECONE_INDEX_NAME")
        
        self.index_name = name
        self.agent_name = agent_name
        self.conversation_id = conversation_id

        # Initialize Supabase client for manual message saving
        self.supabase_client = SupabaseClient()

        # Initialize FastEmbed embedder
        self.embedder = FastEmbedEmbedder()
        
        # Create Pinecone vector DB with FastEmbed embedder
        self.vector_db = PineconeDb(
            name=self.index_name,
            dimension=settings.PINECONE_DIMENSION,
            metric=settings.PINECONE_METRIC,
            spec={"serverless": {"cloud": settings.PINECONE_CLOUD, "region": settings.PINECONE_REGION}},
            api_key=settings.PINECONE_API_KEY,
            embedder=self.embedder,  # Use FastEmbed for local embeddings
            use_hybrid_search=False,  # Can enable if needed, but requires sparse vectors
        )
        
        # Create knowledge base with optimized max_results to prevent context overflow
        self.knowledge = Knowledge(
            name="Knowledge Base",
            vector_db=self.vector_db,
            max_results=25  # Reduced from 50 to 25 - still handles multi-meeting queries while preventing context overflow
        )
        
        # Metadata registration flag - will be registered lazily on first async query
        self._metadata_registered = False
        self._metadata_registration_task = None
        
        # Initialize database for chat history (session-level persistence)
        # Note: Using Supabase REST API for chat history instead of direct database connection
        # This is more reliable and follows Supabase best practices
        db = None
        if enable_chat_history:
            logger.info("Chat history enabled via Supabase REST API (recommended approach)")
            # Chat history will be saved manually via Supabase API calls
        
        # Initialize Groq model (same pattern as llm_client_identifier.py)
        groq_model = Groq(
            id=model_id,
            api_key=settings.GROQ_API_KEY,
            temperature=temperature,
            top_p=top_p
        )
        
        # Create agent with knowledge base and Groq model
        # Note: No database for chat history - using Supabase REST API instead
        self.agent = Agent(
            name=self.agent_name,
            model=groq_model,
            knowledge=self.knowledge,
            search_knowledge=search_knowledge,
            enable_agentic_knowledge_filters=True,  # Agent automatically extracts metadata filters from queries
            db=None,  # No database - chat history handled via Supabase REST API
            add_history_to_context=False,  # Manual history management
            num_history_runs=0,  # No automatic history
            store_tool_messages=False,  # Don't store tool messages (knowledge search tools) to prevent context bloat
            markdown=True,
            debug_mode=settings.DEBUG,
            instructions="""You are an expert meeting transcript analyst for a digital agency.

GOAL: Answer questions about meeting transcripts by searching the knowledge base and providing comprehensive, accurate responses in natural, conversational language.

KNOWLEDGE BASE:
- Contains meeting transcripts from Fireflies (stored in Pinecone vector database)
- Transcripts include metadata: meeting_id, date, client (list), title, participants, date_timestamp
- Client metadata is a LIST that can contain multiple clients (e.g., ["EverMe", "KingStreetMedia"])
- You have access to complete meeting transcripts with full conversation context

SEARCH STRATEGY (CRITICAL - ALWAYS USE BOTH):
1. **ALWAYS use semantic search (RAG)** - This is your primary search method that finds relevant content based on meaning, not just metadata
2. **Use metadata filtering as a supplement** - When questions mention specific clients or dates, use metadata filters to narrow results, BUT always combine with semantic search
3. **For internal meetings or untitled meetings** - These may have empty or incomplete client metadata, so semantic search is ESSENTIAL
4. **For complex queries** - Even when metadata filters are applied, semantic search ensures you don't miss relevant context

METADATA FILTERING (SUPPLEMENTARY):
- When questions mention a CLIENT NAME (e.g., "Ascend", "EverMe", "HME"), you can filter by client metadata
- Note: Client metadata is a LIST - a meeting can have multiple clients (e.g., ["EverMe", "KingStreetMedia"])
- When filtering by client="EverMe", it will match records where "EverMe" is in the client list

DATE FILTERING (CRITICAL - READ CAREFULLY):
- The metadata has TWO date fields: `date` (string) and `date_timestamp` (number)
- For DATE RANGE queries (e.g., "last week", "between Nov 5-11", "after Nov 1", "previous week"):
  - **MUST use `date_timestamp` field with numeric values** (Unix timestamps)
  - Use operators: `$gte` (greater than or equal), `$lte` (less than or equal)
  - Example: `{'date_timestamp': {'$gte': 1730419200, '$lte': 1731024000}}`
  - **NEVER use `date` field with $gte/$lte operators** - it will fail with "Bad Request" error!
- For EXACT DATE matches (e.g., "meetings on November 5"):
  - Can use `date` field with exact match: `{'date': '2025-11-05'}`
  - Or use `date_timestamp` with exact match: `{'date_timestamp': 1730419200}`
- When in doubt, use `date_timestamp` for all date filtering to avoid errors

COMMON DATE FILTERING MISTAKES TO AVOID:
- ❌ WRONG: `{'date': {'$gte': '2025-11-05'}}` - String dates don't work with comparison operators
- ❌ WRONG: `{'date': {'$gte': '2025-11-05', '$lte': '2025-11-11'}}` - Will cause "Bad Request" error
- ✅ CORRECT: `{'date_timestamp': {'$gte': 1730419200}}` - Numeric timestamps work with comparison operators
- ✅ CORRECT: `{'date': '2025-11-05'}` - String dates work for exact matches only

FILTER ERROR HANDLING:
- If a metadata filter fails (e.g., "Bad Request" error from Pinecone), fall back to semantic search only
- Never retry the same failed filter - it will fail again
- When date range filters fail, try using semantic search with date keywords in the query instead
- Always prioritize getting results over perfect filtering - semantic search is more reliable

SEARCH RETRY STRATEGY (CRITICAL - DON'T GIVE UP TOO EARLY):
- If your FIRST search with filters returns NO RESULTS or insufficient context, you MUST try again with different strategies
- Make AT LEAST 2-3 additional tool calls with different filter combinations before concluding no results exist
- Your date range filtering is working correctly - if you don't find results, try these strategies:

STRATEGY 1 - Broaden Date Range:
- If searching "Nov 5-11" returns nothing, try:
  - Broader range: "Nov 1-15" or "Nov 1-20"
  - Or try individual dates: "Nov 5", "Nov 6", "Nov 7", etc.
  - Or try week-based: "first week of November", "second week of November"

STRATEGY 2 - Try Different Filter Combinations:
- If client + date range returns nothing, try:
  - Just client filter (no date)
  - Just date range (no client)
  - Broader date range with same client
  - Different date ranges (previous week, next week, etc.)

STRATEGY 3 - Semantic Search Fallback:
- If all filtered searches return nothing, use pure semantic search with date keywords
- Example: Search for "EverMe meetings November" without filters
- Semantic search can find meetings even if metadata is incomplete

STRATEGY 4 - Multiple Specific Dates:
- Instead of date ranges, try searching individual dates one by one
- Example: Search "Nov 5", then "Nov 6", then "Nov 7" separately
- This ensures you don't miss meetings due to date range boundaries

IMPORTANT RETRY RULES:
- ✅ DO retry with different date ranges if first search returns nothing
- ✅ DO try individual dates if date ranges don't work
- ✅ DO try different filter combinations (client only, date only, both, etc.)
- ✅ DO make 2-3 additional attempts before concluding no results exist
- ❌ DON'T give up after just one search attempt
- ❌ DON'T assume "no results" means no meetings exist - try different approaches first
- ❌ DON'T retry the exact same filter that already failed

EXAMPLE RETRY WORKFLOW:
1. First attempt: `{'client': 'EverMe', 'date_timestamp': {'$gte': X, '$lte': Y}}` → No results
2. Second attempt: `{'client': 'EverMe'}` (no date filter) → Check results
3. Third attempt: `{'date_timestamp': {'$gte': X-7, '$lte': Y+7}}` (broader range) → Check results
4. Fourth attempt: Pure semantic search with "EverMe meetings November" → Check results
5. Only after all attempts: Conclude if no meetings found

- Metadata filtering should be combined with semantic search, not replace it

WHY SEMANTIC SEARCH IS CRITICAL:
- Many meetings are untitled or have incomplete metadata
- Internal meetings (only fruitbowl/gmail participants) may not have client metadata
- Metadata filtering alone can miss relevant content
- Semantic search finds content by meaning, ensuring comprehensive results
- Always prioritize semantic search, use metadata filters to narrow when appropriate

SEARCH WORKFLOW:
1. Extract any metadata filters from the query (client names, dates, etc.)
2. Perform semantic search (RAG) with filters - this is your primary search method
3. **CRITICAL**: If the first search returns NO RESULTS or insufficient context:
   - Make 2-3 additional attempts with different filter strategies (see SEARCH RETRY STRATEGY below)
   - Try broader date ranges, individual dates, different filter combinations
   - Don't give up after just one attempt!
4. If metadata filters are available, apply them to narrow results, BUT still use semantic search
5. Retrieve the most relevant meeting content from both semantic matches and metadata-filtered results
6. Consider all retrieved context when formulating your answer
7. Only conclude "no meetings found" after trying multiple search strategies

RESPONSE REQUIREMENTS:
- Provide detailed, comprehensive answers based on the retrieved transcript content
- Write in natural, conversational language - avoid technical jargon like "chunks", "metadata", "vectors", etc.
- Include specific details: dates, participants, meeting titles, and key discussion points
- Cite meetings naturally (e.g., "In the meeting on [date] with [client]..." or "During the [title] meeting...")
- If multiple meetings are relevant, summarize across all of them
- If no relevant information is found, clearly state that
- Be precise and factual - only use information from the retrieved transcripts
- Use direct quotes when providing specific statements from participants
- Never mention technical implementation details (chunks, indices, metadata fields, etc.) to the user

MULTI-MEETING QUERIES:
- For questions spanning multiple meetings (e.g., "What was discussed with Client X last week?"):
  - Use semantic search to find all relevant meetings
  - Optionally use metadata filters to narrow down to relevant client/date range
  - Search comprehensively across all relevant meetings
  - Synthesize information from multiple meetings
  - Provide a comprehensive summary covering all relevant meetings
  - Group information by meeting or topic as appropriate

RESPONSE STYLE:
- Write as if you were a knowledgeable colleague summarizing meetings
- Use natural language - never say "chunk 7" or "according to metadata"
- Instead say: "In the meeting transcript..." or "According to the discussion..."
- Focus on what was said, who said it, and when it happened
- Provide context and background naturally

IMPORTANT:
- **ALWAYS use semantic search (RAG) as your primary search method**
- Metadata filtering is supplementary - use it to narrow results when appropriate, but never rely on it alone
- For internal meetings, untitled meetings, or complex queries, semantic search is essential
- Always base your answers on the retrieved transcript content
- If you don't have enough context, say so clearly
- Be thorough - the knowledge base contains detailed meeting transcripts
- Remember: Users don't see technical details - they see natural, conversational responses"""
        )
        
        logger.info(f"Initialized Agno agent '{agent_name}' connected to index: {self.index_name}")
    
    def query(self, question: str, session_id: Optional[str] = "default") -> str:
        """
        Query the agent with a question (synchronous).
        The agent will automatically search the knowledge base if search_knowledge is enabled.
        
        Note: For metadata registration, use async methods (aquery/astream_query) which properly
        register metadata filters. This sync method will work but metadata filters may not be
        registered until the first async call.
        
        Args:
            question: User question/query
            session_id: Session ID for maintaining conversation history (default: "default")
                       Use the same session_id across multiple queries to maintain context
            
        Returns:
            Agent response as string
        """
        try:
            # Try to register metadata if not already registered (sync attempt)
            if not self._metadata_registered:
                try:
                    if hasattr(self.knowledge, 'add_content'):
                        self.knowledge.add_content(
                            text_content="__METADATA_REGISTRATION_ONLY_DO_NOT_USE_IN_SEARCHES__",
                            metadata={
                                "client": ["__dummy__"],
                                "date": "2000-01-01",
                                "date_timestamp": 946684800,
                                "title": "__dummy__",
                                "meeting_id": "__dummy__",
                                "participants": ["__dummy__"]
                            }
                        )
                        logger.info(f"Registered metadata filter keys via dummy record (sync, date: 2000-01-01)")
                        self._metadata_registered = True
                except Exception as e:
                    # If sync registration fails (e.g., method is async), that's okay
                    # It will be registered on first async call
                    logger.debug(f"Sync metadata registration skipped (will register on async call): {e}")
            
            response = self.agent.run(question, session_id=session_id)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Error querying agent: {e}")
            raise
    
    def print_response(self, question: str, session_id: Optional[str] = "default") -> None:
        """
        Query the agent and print the response.
        
        Args:
            question: User question/query
            session_id: Session ID for maintaining conversation history (default: "default")
        """
        try:
            self.agent.print_response(question, session_id=session_id)
        except Exception as e:
            logger.error(f"Error printing agent response: {e}")
            raise
    
    async def aquery(self, question: str, session_id: Optional[str] = "default") -> str:
        """
        Async query the agent with a question.
        
        Args:
            question: User question/query
            session_id: Session ID for maintaining conversation history (default: "default")
            
        Returns:
            Agent response as string
        """
        try:
            # Ensure metadata is registered before first query
            await self._ensure_metadata_registered()
            
            response = await self.agent.arun(question, session_id=session_id)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Error in async query: {e}")
            raise
    
    async def _ensure_metadata_registered(self):
        """
        Lazy registration of metadata filters.
        Called before first query to register metadata schema with Agno.
        """
        if self._metadata_registered:
            return

        # Avoid duplicate registration attempts
        if self._metadata_registration_task and not self._metadata_registration_task.done():
            await self._metadata_registration_task
            return

        # Start metadata registration as a background task
        self._metadata_registration_task = asyncio.create_task(self._register_metadata())
        await self._metadata_registration_task

    async def _register_metadata(self):
        """
        Register metadata filters with Pinecone (async background task).
        """
        # Our required metadata fields
        required_fields = {"client", "date", "date_timestamp", "title", "meeting_id", "participants"}

        try:
            # Check if OUR specific metadata fields are already registered
            valid_keys = self.knowledge.get_filters() if hasattr(self.knowledge, 'get_filters') else None
            if valid_keys:
                # Check if all our required fields are present
                valid_keys_set = set(valid_keys) if isinstance(valid_keys, (list, set)) else set()
                missing_fields = required_fields - valid_keys_set

                if not missing_fields:
                    logger.info(f"All required metadata filters already registered: {sorted(required_fields)}")
                    self._metadata_registered = True
                    return
                else:
                    logger.info(f"Some metadata filters missing. Registered: {valid_keys_set}, Missing: {missing_fields}")
            else:
                logger.info("No metadata filters registered yet")
        except Exception as e:
            logger.debug(f"Could not check existing filters: {e}")

        try:
            # Register metadata filter keys by adding a dummy record
            # This is required because Agno only discovers metadata fields through add_content()
            # The dummy record uses old date (2000) and dummy values that won't match real queries
            if hasattr(self.knowledge, 'add_content_async'):
                await self.knowledge.add_content_async(
                    text_content="__METADATA_REGISTRATION_ONLY_DO_NOT_USE_IN_SEARCHES__",
                    metadata={
                        "client": ["__dummy__"],  # Client is a list (can contain multiple clients)
                        "date": "2000-01-01",  # Old date that won't match real queries
                        "date_timestamp": 946684800,  # Jan 1, 2000 timestamp
                        "title": "__dummy__",
                        "meeting_id": "__dummy__",
                        "participants": ["__dummy__"]
                    }
                )
                logger.info(f"Registered metadata filter keys via dummy record: {sorted(required_fields)} (date: 2000-01-01, won't interfere)")
                self._metadata_registered = True
            elif hasattr(self.knowledge, 'add_content'):
                # Try sync version
                self.knowledge.add_content(
                    text_content="__METADATA_REGISTRATION_ONLY_DO_NOT_USE_IN_SEARCHES__",
                    metadata={
                        "client": ["__dummy__"],
                        "date": "2000-01-01",
                        "date_timestamp": 946684800,
                        "title": "__dummy__",
                        "meeting_id": "__dummy__",
                        "participants": ["__dummy__"]
                    }
                )
                logger.info(f"Registered metadata filter keys via dummy record: {sorted(required_fields)} (date: 2000-01-01, won't interfere)")
                self._metadata_registered = True

            # Verify registration
            try:
                valid_keys = self.knowledge.get_filters() if hasattr(self.knowledge, 'get_filters') else None
                if valid_keys:
                    valid_keys_set = set(valid_keys) if isinstance(valid_keys, (list, set)) else set()
                    our_fields_registered = required_fields.intersection(valid_keys_set)
                    if our_fields_registered:
                        logger.info(f"✓ Verified our metadata filters are registered: {sorted(our_fields_registered)}")
                    else:
                        logger.warning(f"⚠ Registration may have failed - our fields not found in: {valid_keys}")
            except:
                pass

        except Exception as e:
            logger.warning(f"Failed to register metadata via dummy record: {e}")
            # Check if filters were registered anyway
            try:
                valid_keys = self.knowledge.get_filters() if hasattr(self.knowledge, 'get_filters') else None
                if valid_keys:
                    valid_keys_set = set(valid_keys) if isinstance(valid_keys, (list, set)) else set()
                    our_fields_registered = required_fields.intersection(valid_keys_set)
                    if our_fields_registered:
                        logger.info(f"Metadata filters registered (found our fields): {sorted(our_fields_registered)}")
                        self._metadata_registered = True
            except:
                pass
    
    async def astream_query(self, question: str, session_id: Optional[str] = "default", conversation_id: Optional[str] = None):
        """
        Async streaming query the agent with a question.
        Yields chunks of the response as they are generated.

        Args:
            question: User question/query
            session_id: Session ID for maintaining conversation history (default: "default")
            conversation_id: Supabase conversation ID for saving messages

        Yields:
            Chunks of agent response as strings
        """
        # Store conversation_id for message saving
        self.conversation_id = conversation_id

        # Start metadata registration in background (non-blocking)
        metadata_task = asyncio.create_task(self._ensure_metadata_registered())

        # Load conversation history from Supabase and add to context
        conversation_history = ""
        logger.info(f"Loading conversation history - conversation_id: {conversation_id}, client configured: {self.supabase_client.is_configured() if self.supabase_client else False}")

        if conversation_id and self.supabase_client.is_configured():
            try:
                # Get only the last 10 messages to prevent context overflow (optimized)
                messages = self.supabase_client.get_messages(conversation_id, limit=10)
                logger.info(f"Loaded {len(messages)} messages for conversation {conversation_id}")

                # Format as conversation history
                history_parts = []
                for msg in messages:
                    if msg['role'] == 'user':
                        history_parts.append(f"User: {msg['content']}")
                    elif msg['role'] == 'assistant':
                        history_parts.append(f"Assistant: {msg['content']}")

                if history_parts:
                    conversation_history = "\n\nPrevious conversation:\n" + "\n".join(history_parts) + "\n\n"
                    logger.info(f"Added conversation history with {len(history_parts)} messages")
                else:
                    logger.info("No conversation history to add")
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")
        else:
            logger.info("Skipping conversation history load - missing conversation_id or Supabase client not configured")

        # Combine history with current question
        full_question = conversation_history + "Current question: " + question
        try:
            # Ensure metadata is registered before first query
            await self._ensure_metadata_registered()
            
            full_response = ""
            async for chunk in self.agent.arun(full_question, session_id=session_id, stream=True):
                if hasattr(chunk, 'content'):
                    full_response += chunk.content
                    yield chunk.content
                else:
                    chunk_str = str(chunk)
                    full_response += chunk_str
                    yield chunk_str

            # Assistant response is saved in main.py after streaming completes
            # No need to save here to avoid duplicates
        except Exception as e:
            logger.error(f"Error in async streaming query: {e}")
            raise


# Convenience function to create a default agent instance
def create_agent(
    index_name: Optional[str] = None,
    agent_name: str = "Knowledge Assistant",
    model_id: str = "openai/gpt-oss-120b"  # Default Groq model ID
) -> AgnoAgentService:
    """
    Create a default Agno agent instance.
    
    Args:
        index_name: Name of existing Pinecone index
        agent_name: Name of the agent
        model_id: Groq model ID (e.g., "openai/gpt-oss-120b", "llama-3.1-70b-versatile")
        
    Returns:
        AgnoAgentService instance
    """
    return AgnoAgentService(
        index_name=index_name,
        agent_name=agent_name,
        model_id=model_id
    )

