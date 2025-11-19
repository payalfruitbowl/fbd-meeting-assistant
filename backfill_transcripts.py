"""
Backfill historical transcripts to Pinecone.

This script processes transcripts in 10-day batches, going backwards from today.
It saves progress to a file so it can resume if interrupted.

Usage:
    # Test with 20 days (2 batches)
    python backfill_transcripts.py --days 20
    
    # Process 1 year (365 days, ~36 batches)
    python backfill_transcripts.py --days 365
    
    # Resume from last progress
    python backfill_transcripts.py --resume
"""
import asyncio
import logging
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
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

# Progress file
PROGRESS_FILE = Path("backfill_progress.txt")
BATCH_SIZE_DAYS = 10  # Process 10 days per batch

# Reuse functions from test_pinecone_setup.py
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


def load_progress() -> Optional[datetime]:
    """Load last processed date from progress file."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, 'r') as f:
                date_str = f.read().strip()
                if date_str:
                    return datetime.strptime(date_str, "%Y-%m-%d")
        except Exception as e:
            logger.warning(f"Failed to load progress: {e}")
    return None


def save_progress(date: datetime):
    """Save last processed date to progress file."""
    try:
        with open(PROGRESS_FILE, 'w') as f:
            f.write(date.strftime("%Y-%m-%d"))
        logger.info(f"Progress saved: {date.date()}")
    except Exception as e:
        logger.warning(f"Failed to save progress: {e}")


async def process_batch(
    fireflies_client: FirefliesClient,
    pinecone_client: PineconeClient,
    data_processor: DataProcessor,
    start_date: datetime,
    end_date: datetime
) -> tuple[int, int]:
    """
    Process a single batch (10 days) of transcripts.
    
    Returns:
        Tuple of (transcripts_processed, chunks_created)
    """
    logger.info("=" * 60)
    logger.info(f"Processing batch: {start_date.date()} to {end_date.date()}")
    logger.info("=" * 60)
    
    from_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    # Fetch transcript list
    transcript_list = await fireflies_client.get_transcripts_list_between(
        from_date_str,
        to_date_str,
        limit=50
    )
    
    if not transcript_list:
        logger.info(f"No transcripts found for {start_date.date()} to {end_date.date()}")
        return 0, 0
    
    logger.info(f"Found {len(transcript_list)} transcripts")
    
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
    
    # Process and store transcripts (EXACT same logic as test_pinecone_setup.py)
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
    
    return len(full_transcripts), total_chunks


async def backfill_transcripts(total_days: int, resume: bool = False, start_date: Optional[datetime] = None):
    """
    Main backfill function.
    
    Args:
        total_days: Total number of days to process (going backwards from start date)
        resume: If True, resume from last progress file
        start_date: Optional start date (YYYY-MM-DD format string or datetime). If not provided, uses today or resume date.
    """
    logger.info("=" * 60)
    logger.info("Starting Transcript Backfill")
    logger.info("=" * 60)
    
    # Initialize clients
    logger.info("Initializing clients...")
    fireflies_client = FirefliesClient()
    pinecone_client = PineconeClient()
    data_processor = DataProcessor()
    
    # Check if index exists
    if not settings.PINECONE_INDEX_NAME:
        logger.error("PINECONE_INDEX_NAME not set in environment variables")
        return
    
    index_name = settings.PINECONE_INDEX_NAME
    logger.info(f"Using Pinecone index: {index_name}")
    
    try:
        existing_indexes = pinecone_client.list_indexes()
        if index_name not in existing_indexes:
            logger.info(f"Index '{index_name}' does not exist. Creating...")
            pinecone_client.create_index(index_name)
            logger.info(f"Index '{index_name}' created successfully")
        else:
            logger.info(f"Index '{index_name}' already exists")
            if not pinecone_client.index:
                pinecone_client.index = pinecone_client.pc.Index(index_name)
    except Exception as e:
        logger.error(f"Error checking/creating index: {e}")
        return
    
    # Determine start date
    end_date = datetime.utcnow()
    
    if start_date:
        # Use provided start date
        if isinstance(start_date, str):
            end_date = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            end_date = start_date
        logger.info(f"Starting from specified date: {end_date.date()}")
    elif resume:
        last_date = load_progress()
        if last_date:
            end_date = last_date
            logger.info(f"Resuming from: {end_date.date()}")
        else:
            logger.info("No progress file found, starting from today")
    else:
        logger.info(f"Starting fresh from: {end_date.date()}")
    
    # Calculate target start date (going backwards)
    target_start_date = end_date - timedelta(days=total_days)
    logger.info(f"Target date range: {target_start_date.date()} to {end_date.date()}")
    logger.info(f"Batch size: {BATCH_SIZE_DAYS} days")
    
    # Process batches
    current_end = end_date
    batch_num = 1
    total_transcripts = 0
    total_chunks = 0
    
    while current_end > target_start_date:
        # Calculate batch start date
        batch_start = current_end - timedelta(days=BATCH_SIZE_DAYS)
        if batch_start < target_start_date:
            batch_start = target_start_date
        
        # Process batch
        transcripts, chunks = await process_batch(
            fireflies_client,
            pinecone_client,
            data_processor,
            batch_start,
            current_end
        )
        
        total_transcripts += transcripts
        total_chunks += chunks
        
        # Save progress
        save_progress(batch_start)
        
        # Move to next batch (going backwards)
        current_end = batch_start
        batch_num += 1
        
        logger.info(f"\nBatch {batch_num - 1} complete. Total: {total_transcripts} transcripts, {total_chunks} chunks")
        logger.info(f"Remaining: {(current_end - target_start_date).days} days\n")
    
    logger.info("=" * 60)
    logger.info("Backfill Complete!")
    logger.info(f"Total transcripts processed: {total_transcripts}")
    logger.info(f"Total chunks created: {total_chunks}")
    logger.info("=" * 60)
    
    # Clean up progress file
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        logger.info("Progress file cleaned up")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical transcripts to Pinecone")
    parser.add_argument(
        "--days",
        type=int,
        default=20,
        help="Number of days to process (default: 20 for testing)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last progress file"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date to begin processing from (YYYY-MM-DD format). Goes backwards from this date."
    )
    
    args = parser.parse_args()
    
    # Verify environment variables
    import os
    if not os.getenv("PINECONE_API_KEY"):
        logger.error("PINECONE_API_KEY not found in environment variables")
        exit(1)
    
    if not os.getenv("FIREFLIES_API_KEY"):
        logger.error("FIREFLIES_API_KEY not found in environment variables")
        exit(1)
    
    # Parse start date if provided
    start_date = None
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        except ValueError:
            logger.error(f"Invalid start date format: {args.start_date}. Use YYYY-MM-DD format.")
            exit(1)
    
    # Run backfill
    asyncio.run(backfill_transcripts(args.days, resume=args.resume, start_date=start_date))

