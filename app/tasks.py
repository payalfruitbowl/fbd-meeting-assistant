"""
Celery tasks for background processing.
"""
import asyncio
import logging
from datetime import datetime, timedelta
import gc
from typing import List, Dict, Any

from app.celery_app import celery_app
from app.services.fireflies_client import FirefliesClient
from app.services.pinecone_client import PineconeClient
from app.services.data_processor import DataProcessor
from app.services.transcript_cleaner import TranscriptCleaner

logger = logging.getLogger(__name__)


# Helper functions (same as in main.py)
def chunk_text_generator(text: str, chunk_size: int = 500, overlap: int = 50):
    """
    Generate chunks incrementally (yields one at a time).
    This is memory-efficient - doesn't create all chunks at once.
    """
    if not text:
        return

    if len(text) <= chunk_size:
        yield text
        return

    if overlap >= chunk_size:
        overlap = chunk_size // 4

    start = 0
    step = chunk_size - overlap

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            yield chunk
        start += step
        if start >= len(text):
            break


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


async def run_daily_sync_async():
    """
    Async function that runs the actual daily sync.
    This is the core sync logic moved from main.py.
    """
    try:
        logger.info("=" * 60)
        logger.info("Starting daily sync (Celery worker)")
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

            # Process transcripts one at a time: fetch → process → upsert → clear
            for transcript_info in transcript_list:
                transcript_id = transcript_info.get("id")
                if not transcript_id:
                    continue

                # Fetch full transcript details for THIS transcript only
                try:
                    full_transcript = await fireflies_client.get_transcript_details(transcript_id)
                    full_transcript.update(transcript_info)
                except Exception as e:
                    logger.warning(f"Failed to fetch full transcript {transcript_id}: {e}")
                    continue

                # Extract text (with cleaning) - do this immediately
                transcript_text = extract_transcript_text(full_transcript, clean=True)
                if not transcript_text.strip():
                    logger.warning(f"Skipping transcript {transcript_id}: No text content")
                    del full_transcript
                    continue

                # Identify clients (need full_transcript for this)
                clients = identify_clients(full_transcript, data_processor)
                if clients:
                    logger.info(f"  Identified clients: {', '.join(clients)}")

                # Extract date and create numeric timestamp for filtering
                date_str = full_transcript.get("dateString") or full_transcript.get("date", "")
                date_timestamp = None

                if isinstance(date_str, str) and "T" in date_str:
                    date_str = date_str.split("T")[0]
                    try:
                        from datetime import datetime as dt
                        date_obj = dt.strptime(date_str, "%Y-%m-%d")
                        date_timestamp = int(date_obj.timestamp())
                    except Exception as e:
                        logger.warning(f"Failed to parse date {date_str}: {e}")
                elif date_str:
                    try:
                        from datetime import datetime as dt
                        date_obj = dt.strptime(date_str, "%Y-%m-%d")
                        date_timestamp = int(date_obj.timestamp())
                    except:
                        pass

                # Get title and participants
                title = full_transcript.get("title", "Untitled Meeting")
                participants = full_transcript.get("participants", [])
                if not participants and full_transcript.get("meeting_attendees"):
                    participants = [
                        attendee.get("email")
                        for attendee in full_transcript.get("meeting_attendees", [])
                        if attendee.get("email")
                    ]

                # Clear full_transcript from memory NOW
                del full_transcript

                # Estimate total chunks for metadata
                chunk_size = 2500
                overlap = 200
                step = chunk_size - overlap
                estimated_total_chunks = max(1, (len(transcript_text) + step - 1) // step)
                
                # Use generator to chunk text incrementally
                chunk_generator = chunk_text_generator(transcript_text, chunk_size=chunk_size, overlap=overlap)
                
                # Process chunks in small batches
                CHUNK_BATCH_SIZE = 10
                upsert_batch_size = 50
                
                batch_records = []
                chunk_index = 0
                total_chunks_processed = 0
                
                # Process chunks as they're generated
                for chunk_text_content in chunk_generator:
                    record_id = f"meeting_{transcript_id}#chunk_{chunk_index}"

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
                            "chunk_index": chunk_index,
                            "total_chunks": estimated_total_chunks,
                            "content": chunk_text_content,
                            "chunk_text": chunk_text_content[:200]
                        }
                    }
                    batch_records.append(record)
                    chunks_created += 1
                    chunk_index += 1
                    total_chunks_processed += 1

                    # When batch reaches size, upsert and clear immediately
                    if len(batch_records) >= CHUNK_BATCH_SIZE:
                        for upsert_start in range(0, len(batch_records), upsert_batch_size):
                            upsert_batch = batch_records[upsert_start:upsert_start + upsert_batch_size]
                            try:
                                pinecone_client.upsert_texts(upsert_batch)
                                first_chunk_idx = chunk_index - len(batch_records) + upsert_start
                                last_chunk_idx = first_chunk_idx + len(upsert_batch) - 1
                                logger.info(f"    ✓ Upserted {len(upsert_batch)} records (chunks {first_chunk_idx}-{last_chunk_idx})")
                            except Exception as e:
                                logger.error(f"    ✗ Failed to upsert batch: {e}")

                        del batch_records
                        batch_records = []
                        gc.collect()

                # Upsert any remaining chunks
                if batch_records:
                    for upsert_start in range(0, len(batch_records), upsert_batch_size):
                        upsert_batch = batch_records[upsert_start:upsert_start + upsert_batch_size]
                        try:
                            pinecone_client.upsert_texts(upsert_batch)
                            first_chunk_idx = chunk_index - len(batch_records) + upsert_start
                            last_chunk_idx = first_chunk_idx + len(upsert_batch) - 1
                            logger.info(f"    ✓ Upserted {len(upsert_batch)} records (chunks {first_chunk_idx}-{last_chunk_idx})")
                        except Exception as e:
                            logger.error(f"    ✗ Failed to upsert batch: {e}")
                    del batch_records
                    gc.collect()
                
                logger.info(f"  Transcript {transcript_id}: {total_chunks_processed} chunks processed")

                transcripts_processed += 1
                
                # Clear ALL transcript data from memory
                del transcript_text
                del clients
                del participants
                del title
                del date_str
                
                # Final garbage collection after each transcript
                gc.collect()

            logger.info(f"✓ Successfully stored {chunks_created} chunks from {transcripts_processed} transcripts")
        else:
            logger.info("No new transcripts found for the past day")

        logger.info("=" * 60)
        logger.info("Daily sync completed (Celery worker)")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Error in daily sync: {str(e)}", exc_info=True)
        raise


@celery_app.task(name="app.tasks.daily_sync_task", bind=True)
def daily_sync_task(self):
    """
    Celery task that runs the daily sync.
    This runs in a separate worker process with its own memory space.
    """
    try:
        # Run the async function
        asyncio.run(run_daily_sync_async())
        return {"status": "success", "message": "Daily sync completed"}
    except Exception as e:
        logger.error(f"Daily sync task failed: {e}", exc_info=True)
        # Retry the task once on failure
        raise self.retry(exc=e, countdown=60, max_retries=1)


