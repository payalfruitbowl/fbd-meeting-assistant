"""
Test script for Pinecone setup and transcript storage.

This script:
1. Fetches last 10 days meeting transcripts from Fireflies (with caching)
2. Chunks transcripts into smaller pieces
3. Stores chunks in Pinecone with metadata
4. Tests deletion of records

Run this to test PineconeClient functionality before using Agno agent.
"""
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from app.config import settings
from app.services.fireflies_client import FirefliesClient
from app.services.pinecone_client import PineconeClient
from app.services.data_processor import DataProcessor
from app.services.transcript_cleaner import TranscriptCleaner

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split text into fixed-size chunks with overlap.
    
    Args:
        text: Text to chunk
        chunk_size: Fixed size of each chunk (characters)
        overlap: Number of characters to overlap between chunks
        
    Returns:
        List of text chunks (all chunks will be approximately chunk_size)
    """
    if not text:
        return []
    
    if len(text) <= chunk_size:
        return [text]
    
    # Safety check: ensure overlap is less than chunk_size
    if overlap >= chunk_size:
        overlap = chunk_size // 4  # Default to 25% overlap
    
    chunks = []
    start = 0
    step = chunk_size - overlap  # How much to advance each iteration
    
    while start < len(text):
        end = start + chunk_size
        
        # Extract chunk (fixed size)
        chunk = text[start:end]
        
        # Only add non-empty chunks
        if chunk.strip():
            chunks.append(chunk)
        
        # Move to next position with overlap
        start += step
        
        # Safety: ensure we make progress
        if start >= len(text):
            break
    
    return chunks


def extract_transcript_text(transcript: Dict[str, Any], clean: bool = True) -> str:
    """
    Extract formatted text from transcript sentences.
    Optionally cleans by merging consecutive same-speaker messages.
    
    Args:
        transcript: Transcript dictionary with sentences
        clean: Whether to clean/merge consecutive same-speaker messages
        
    Returns:
        Formatted text string
    """
    # Clean transcript if requested
    if clean:
        transcript = TranscriptCleaner.clean_transcript(transcript)
        return TranscriptCleaner.format_cleaned_transcript_text(transcript)
    
    # Original logic (no cleaning)
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
    """
    Identify ALL clients from transcript by extracting external domains from participant emails.
    Returns a list of client identifiers (domain names without TLD, capitalized).
    
    Strategy:
    1. First try to extract client from title (if title contains client name)
    2. Extract ALL external domains from participant emails (excluding internal and generic providers)
    3. Return list of all external client domains found
    
    Args:
        transcript: Transcript dictionary
        data_processor: DataProcessor instance
        
    Returns:
        List of client identifiers (e.g., ["EverMe", "KingStreetMedia"])
    """
    clients = []
    
    # Generic email providers to exclude (not considered client domains)
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
            # Normalize brand name (remove spaces, capitalize)
            brand_normalized = brand.strip().replace(" ", "").replace("-", "")
            if brand_normalized:
                clients.append(brand_normalized)
    
    # Step 2: Extract ALL external domains from participant emails
    participants = transcript.get("participants", [])
    meeting_attendees = transcript.get("meeting_attendees", [])
    
    # Get all unique emails
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
    
    # Extract external domains (exclude internal team and generic providers)
    external_domains = set()
    for email in all_emails:
        if "@" in email:
            domain = email.split("@")[1].lower()
            # Skip internal domains
            if data_processor._is_internal_team(email):
                continue
            # Skip generic email providers
            if domain in generic_providers:
                continue
            # Add external domain
            external_domains.add(domain)
    
    # Convert domains to client identifiers (domain without TLD, capitalized)
    for domain in external_domains:
        # Extract domain name (part before first dot, or full domain if no dot)
        domain_parts = domain.split(".")
        if domain_parts:
            # Use first part (e.g., "everme" from "everme.ai")
            domain_name = domain_parts[0]
            # Capitalize appropriately (e.g., "everme" -> "EverMe", "kingstreetmedia" -> "KingStreetMedia")
            # Simple capitalization: first letter uppercase, rest lowercase
            # For better results, we can use title case
            client_name = domain_name.title()
            if client_name not in clients:
                clients.append(client_name)
    
    # If no clients found, return empty list (will be stored as empty list in metadata)
    # This allows the agent to still find these meetings via semantic search
    return clients


# Cache directory for transcripts
CACHE_DIR = Path("cache/transcripts")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_cache_filename(start_date: datetime, end_date: datetime) -> Path:
    """Generate cache filename based on date range."""
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    return CACHE_DIR / f"transcripts_{start_str}_{end_str}.json"


def load_cached_transcripts(start_date: datetime, end_date: datetime) -> Optional[List[Dict[str, Any]]]:
    """Load transcripts from cache if available."""
    cache_file = get_cache_filename(start_date, end_date)
    if cache_file.exists():
        try:
            logger.info(f"Loading transcripts from cache: {cache_file}")
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
    return None


def save_transcripts_to_cache(transcripts: List[Dict[str, Any]], start_date: datetime, end_date: datetime):
    """Save transcripts to cache."""
    cache_file = get_cache_filename(start_date, end_date)
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(transcripts, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(transcripts)} transcripts to cache: {cache_file}")
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


async def fetch_and_store_transcripts():
    """
    Main function to fetch transcripts and store in Pinecone.
    """
    logger.info("=" * 60)
    logger.info("Starting Pinecone setup test")
    logger.info("=" * 60)
    
    # Initialize clients
    logger.info("Initializing clients...")
    fireflies_client = FirefliesClient()
    pinecone_client = PineconeClient()
    data_processor = DataProcessor()
    
    # Check if index exists, create if not
    if not settings.PINECONE_INDEX_NAME:
        logger.error("PINECONE_INDEX_NAME not set in environment variables")
        return
    
    index_name = settings.PINECONE_INDEX_NAME
    logger.info(f"Using Pinecone index: {index_name}")
    
    # List existing indexes
    try:
        existing_indexes = pinecone_client.list_indexes()
        logger.info(f"Existing indexes: {existing_indexes}")
        
        if index_name not in existing_indexes:
            logger.info(f"Index '{index_name}' does not exist. Creating...")
            pinecone_client.create_index(index_name)
            logger.info(f"Index '{index_name}' created successfully")
        else:
            logger.info(f"Index '{index_name}' already exists")
            # Connect to existing index (v5.4.2 API)
            if not pinecone_client.index:
                pinecone_client.index = pinecone_client.pc.Index(index_name)
                logger.info(f"Connected to existing index: {index_name}")
    except Exception as e:
        logger.error(f"Error checking/creating index: {e}")
        return
    
    # Fetch transcripts from last 10 days
    logger.info("\n" + "=" * 60)
    logger.info("Fetching transcripts from last 10 days...")
    logger.info("=" * 60)
    
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=10)
    
    from_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")
    
    try:
        # Try to load from cache first
        full_transcripts = load_cached_transcripts(start_date, end_date)
        
        if full_transcripts is None:
            # Cache miss - fetch from API
            logger.info("Cache miss - fetching from Fireflies API...")
            
            # Get transcript list
            transcript_list = await fireflies_client.get_transcripts_list_between(
                from_date_str, 
                to_date_str,
                limit=50
            )
            
            logger.info(f"Found {len(transcript_list)} transcripts")
            
            if not transcript_list:
                logger.warning("No transcripts found in the last 10 days")
                return
            
            # Fetch full transcript details
            logger.info("\nFetching full transcript details...")
            full_transcripts = []
            for transcript_info in transcript_list:
                transcript_id = transcript_info.get("id")
                if transcript_id:
                    try:
                        full_transcript = await fireflies_client.get_transcript_details(transcript_id)
                        full_transcript.update(transcript_info)
                        full_transcripts.append(full_transcript)
                        logger.info(f"  ✓ Fetched transcript: {transcript_info.get('title', transcript_id)}")
                    except Exception as e:
                        logger.warning(f"  ✗ Failed to fetch transcript {transcript_id}: {e}")
                        full_transcripts.append(transcript_info)
            
            # Save to cache
            save_transcripts_to_cache(full_transcripts, start_date, end_date)
        else:
            logger.info(f"Loaded {len(full_transcripts)} transcripts from cache")
        
        logger.info(f"Retrieved {len(full_transcripts)} complete transcripts")
        
        # Process and store transcripts
        logger.info("\n" + "=" * 60)
        logger.info("Processing and storing transcripts in Pinecone...")
        logger.info("=" * 60)
        
        all_records = []
        total_chunks = 0
        
        for transcript in full_transcripts:
            transcript_id = transcript.get("id")
            if not transcript_id:
                continue
            
            # Extract text (with cleaning - merges consecutive same-speaker messages)
            sentences = transcript.get("sentences") or []
            original_sentence_count = len(sentences) if sentences else 0
            transcript_text = extract_transcript_text(transcript, clean=True)
            if not transcript_text.strip():
                logger.warning(f"Skipping transcript {transcript_id}: No text content")
                continue
            
            # Log cleaning stats if we have sentences
            if original_sentence_count > 0:
                # Count sentences after cleaning (approximate from text)
                cleaned_line_count = len([line for line in transcript_text.split('\n') if line.strip()])
                if cleaned_line_count < original_sentence_count:
                    logger.debug(f"  Cleaned transcript {transcript_id}: {original_sentence_count} → {cleaned_line_count} messages (merged consecutive same-speaker)")
            
            # Chunk the text (larger chunks for better context)
            chunk_size = 2500  # 2500 characters = better context, fewer records
            overlap = 200  # 200 char overlap to maintain context continuity
            chunks = chunk_text(transcript_text, chunk_size=chunk_size, overlap=overlap)
            logger.info(f"  Transcript {transcript_id}: {len(chunks)} chunks")
            
            # Identify ALL clients (returns list of client identifiers)
            clients = identify_clients(transcript, data_processor)
            if clients:
                logger.info(f"  Identified clients: {', '.join(clients)}")
            else:
                logger.info(f"  No external clients identified (may be internal meeting or untitled)")
            
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
            
            # Get title
            title = transcript.get("title", "Untitled Meeting")
            
            # Extract participants (list of email addresses)
            participants = transcript.get("participants", [])
            if not participants and transcript.get("meeting_attendees"):
                # Fallback to meeting_attendees if participants not available
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
                        "date": date_str,  # String date for display
                        "date_timestamp": date_timestamp,  # Numeric timestamp for filtering
                        "client": clients,  # List of client identifiers (e.g., ["EverMe", "KingStreetMedia"])
                        "title": title,
                        "participants": participants,  # List of participant emails
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "content": chunk_text_content,  # Full text content for Agno to retrieve (critical!)
                        "chunk_text": chunk_text_content[:200]  # First 200 chars for quick reference
                    }
                }
                all_records.append(record)
                total_chunks += 1
        
        logger.info(f"\nTotal chunks to store: {total_chunks}")
        
        # Upsert records in batches
        logger.info("\nUpserting records to Pinecone...")
        batch_size = 50  # Pinecone v5.4.2 can handle up to 100 vectors per batch
        
        for i in range(0, len(all_records), batch_size):
            batch = all_records[i:i + batch_size]
            try:
                pinecone_client.upsert_texts(batch)
                logger.info(f"  ✓ Upserted batch {i//batch_size + 1} ({len(batch)} records)")
            except Exception as e:
                logger.error(f"  ✗ Failed to upsert batch {i//batch_size + 1}: {e}")
        
        logger.info(f"\n✓ Successfully stored {total_chunks} chunks from {len(full_transcripts)} transcripts")
        
        # Get index stats
        logger.info("\n" + "=" * 60)
        logger.info("Index Statistics:")
        logger.info("=" * 60)
        try:
            stats = pinecone_client.get_index_stats()
            logger.info(f"Total vectors: {stats.get('total_vector_count', 'N/A')}")
            if 'namespaces' in stats:
                logger.info(f"Namespaces: {list(stats['namespaces'].keys())}")
        except Exception as e:
            logger.warning(f"Could not get index stats: {e}")
        
        # Test deletion
        logger.info("\n" + "=" * 60)
        logger.info("Testing deletion functionality...")
        logger.info("=" * 60)
        
        if all_records:
            # Test 1: Delete by ID
            test_record = all_records[0]
            test_id = test_record["id"]
            logger.info(f"\nTest 1: Deleting record by ID: {test_id}")
            try:
                pinecone_client.delete_vectors([test_id])
                logger.info(f"  ✓ Successfully deleted record {test_id}")
            except Exception as e:
                logger.error(f"  ✗ Failed to delete record: {e}")
            
            # Test 2: Delete by date filter (delete data from 1 day before the start date)
            # If we fetched last 10 days (e.g., Jan 3-13), delete data from Jan 2 and before
            cutoff_date = (start_date - timedelta(days=1)).strftime("%Y-%m-%d")
            # Create numeric timestamp for filtering (Pinecone requires numbers for $lt/$gt)
            cutoff_timestamp = int((start_date - timedelta(days=1)).timestamp())
            
            logger.info(f"\nTest 2: Deleting records older than {cutoff_date} (timestamp: {cutoff_timestamp})")
            try:
                # Delete all records with date_timestamp less than cutoff_timestamp
                # Pinecone v5.4.2 requires numeric values for $lt/$gt operators
                pinecone_client.delete_by_filter(
                    {"date_timestamp": {"$lt": cutoff_timestamp}}
                )
                logger.info(f"  ✓ Successfully deleted records with date_timestamp < {cutoff_timestamp} (date < {cutoff_date})")
            except Exception as e:
                logger.error(f"  ✗ Failed to delete by date filter: {e}")
        
        logger.info("\n" + "=" * 60)
        logger.info("Test completed!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error in fetch_and_store_transcripts: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Verify environment variables are loaded
    if not os.getenv("PINECONE_API_KEY"):
        logger.error("PINECONE_API_KEY not found in environment variables")
        logger.error("Make sure .env file exists and contains PINECONE_API_KEY")
        exit(1)
    
    if not os.getenv("FIREFLIES_API_KEY"):
        logger.error("FIREFLIES_API_KEY not found in environment variables")
        logger.error("Make sure .env file exists and contains FIREFLIES_API_KEY")
        exit(1)
    
    # Run the async function
    asyncio.run(fetch_and_store_transcripts())

