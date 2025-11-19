"""
Test script to check how far back Fireflies transcripts can be retrieved.

This script:
1. Fetches transcript list from Fireflies for a specific date range
2. Displays summary information about retrieved transcripts
3. Does NOT upsert any data to Pinecone (read-only test)

Use this to verify how far back in history you can retrieve transcripts.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from app.services.fireflies_client import FirefliesClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def format_date_range(start_date: datetime, end_date: datetime) -> tuple[str, str]:
    """
    Format datetime range to Fireflies API ISO format.
    Matches the format used in test_pinecone_setup.py and fireflies_client.py
    
    Args:
        start_date: Start datetime (inclusive)
        end_date: End datetime (inclusive)
        
    Returns:
        Tuple of (from_date_str, to_date_str) in ISO format
    """
    # Format dates in ISO 8601 format: YYYY-MM-DDTHH:mm:ss.000Z
    # Use the same format as existing implementations
    from_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    to_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return from_date_str, to_date_str


async def test_transcript_retrieval(start_date: datetime, end_date: datetime, limit: Optional[int] = 50):
    """
    Test transcript retrieval for a specific date range.
    
    Args:
        start_date: Start date (inclusive) - should be datetime with time component
        end_date: End date (inclusive) - should be datetime with time component
        limit: Maximum number of transcripts to retrieve
    """
    logger.info("=" * 60)
    logger.info("Testing Transcript History Retrieval")
    logger.info("=" * 60)
    logger.info(f"Date Range: {start_date.date()} to {end_date.date()}")
    logger.info(f"Today's Date: {datetime.utcnow().date()}")
    logger.info("")
    
    # Initialize Fireflies client
    fireflies_client = FirefliesClient()
    
    # Format dates for API (same format as test_pinecone_setup.py)
    from_date_str, to_date_str = format_date_range(start_date, end_date)
    logger.info(f"API Request:")
    logger.info(f"  from_date: {from_date_str}")
    logger.info(f"  to_date: {to_date_str}")
    logger.info(f"  limit: {limit}")
    logger.info("")
    
    try:
        # Fetch transcript list
        logger.info("Fetching transcript list from Fireflies...")
        transcript_list = await fireflies_client.get_transcripts_list_between(
            from_date_str,
            to_date_str,
            limit=limit
        )
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Results: Found {len(transcript_list)} transcripts")
        logger.info("=" * 60)
        
        if not transcript_list:
            logger.warning("No transcripts found for the specified date range.")
            logger.info("This could mean:")
            logger.info("  1. No meetings occurred during this period")
            logger.info("  2. Transcripts are not available this far back")
            logger.info("  3. API access limitations")
            return
        
        # Display transcript summary
        logger.info("")
        logger.info("Transcript Summary:")
        logger.info("-" * 60)
        
        for idx, transcript in enumerate(transcript_list, 1):
            transcript_id = transcript.get("id", "N/A")
            title = transcript.get("title", "Untitled Meeting")
            date_str = transcript.get("dateString") or transcript.get("date", "Unknown")
            duration = transcript.get("duration", "Unknown")
            
            # Get participants count
            participants = transcript.get("participants", [])
            meeting_attendees = transcript.get("meeting_attendees", [])
            if not participants and meeting_attendees:
                participants = meeting_attendees
            
            participant_count = len(participants) if isinstance(participants, list) else 0
            
            logger.info(f"[{idx:2d}] {title}")
            logger.info(f"     ID: {transcript_id}")
            logger.info(f"     Date: {date_str}")
            logger.info(f"     Duration: {duration}")
            logger.info(f"     Participants: {participant_count}")
            logger.info("")
        
        logger.info("=" * 60)
        logger.info("Test completed successfully!")
        logger.info("NOTE: No data was upserted to Pinecone (read-only test)")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error fetching transcripts: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Test date range: June 11, 2024
    # Today's date is November 17, 2025 (as specified by user)
    # Create datetime objects with time components (start of day for start, end of day for end)
    # This matches how test_pinecone_setup.py creates dates
    START_DATE = datetime(2025, 1, 1, 0, 0, 0)  # Start of June 11, 2024
    END_DATE = datetime(2025, 1, 10, 23, 59, 59)  # End of June 11, 2024
    
    # Run the test (limit max is 50 per Fireflies API docs)
    asyncio.run(test_transcript_retrieval(START_DATE, END_DATE, limit=50))

