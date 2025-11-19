"""
Test the full pipeline: API → Client Identification → Word Generation
This will help verify everything works end-to-end.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from app.services.fireflies_client import FirefliesClient
from app.services.data_processor import DataProcessor
from app.services.word_generator import WordGenerator

# Load environment variables
load_dotenv()


# Configure logging for test run to show INFO logs from services
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)


def _extract_external_domains_debug(meeting: dict, internal_domains: set) -> set[str]:
    externals = set()
    # participants: list[str] of emails
    for p in meeting.get("participants", []):
        if isinstance(p, str) and "@" in p:
            d = p.split("@")[1].lower().strip()
            if d and d not in internal_domains and d not in {
                "gmail.com","outlook.com","hotmail.com","yahoo.com","icloud.com","aol.com","protonmail.com"
            }:
                externals.add(d)
    # meeting_attendees: list[dict]
    for a in meeting.get("meeting_attendees", []):
        if isinstance(a, dict):
            email = a.get("email","")
            if email and "@" in email:
                d = email.split("@")[1].lower().strip()
                if d and d not in internal_domains and d not in {
                    "gmail.com","outlook.com","hotmail.com","yahoo.com","icloud.com","aol.com","protonmail.com"
                }:
                    externals.add(d)
    # organizer/host hints
    for key in ("organizer_email","host_email"):
        email = meeting.get(key, "")
        if email and "@" in email:
            d = email.split("@")[1].lower().strip()
            if d and d not in internal_domains and d not in {
                "gmail.com","outlook.com","hotmail.com","yahoo.com","icloud.com","aol.com","protonmail.com"
            }:
                externals.add(d)
    return externals


async def test_full_pipeline():
    """Test the complete pipeline from API to Word documents."""
    print("=" * 80)
    print("TESTING FULL PIPELINE")
    print("=" * 80)
    
    try:
        # Step 1: Fetch transcripts (with cache)
        print("\n[1/4] Fetching transcripts from Fireflies API...")
        fireflies_client = FirefliesClient()

        # Simple cache for testing
        import os, json
        cache_dir = "cache"
        cache_path = os.path.join(cache_dir, "transcripts_week.json")
        transcripts = None
        if os.path.exists(cache_path):
            print("Using cached transcripts from cache/transcripts_week.json")
            with open(cache_path, "r", encoding="utf-8") as f:
                transcripts = json.load(f)
        else:
            transcripts = await fireflies_client.get_weekly_transcripts()
            if transcripts:
                os.makedirs(cache_dir, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(transcripts, f, indent=2, ensure_ascii=False)
                print("Cached transcripts to cache/transcripts_week.json")
        
        if not transcripts:
            print("⚠ No transcripts found for the past week.")
            print("   This is normal if there were no meetings.")
            return
        
        print(f"✓ Found {len(transcripts)} transcript(s)")
        
        # Debug: Show domain frequency across all transcripts before LLM
        print("\n[DEBUG] Computing external domain frequencies across transcripts (pre-LLM)...")
        from app.config import settings as app_settings
        domain_counts = {}
        for t in transcripts:
            for d in _extract_external_domains_debug(t, {dom.strip().lower() for dom in app_settings.INTERNAL_DOMAINS.split(',') if dom.strip()}):
                domain_counts[d] = domain_counts.get(d, 0) + 1
        if domain_counts:
            top = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)
            print(f"[DEBUG] External domains by frequency (top 10): {top[:10]}")
        else:
            print("[DEBUG] No external domains detected (all internal/generic).")

        # Step 2: Process and identify clients
        print("\n[2/4] Processing transcripts and identifying clients...")
        data_processor = DataProcessor()
        client_transcripts = await data_processor.filter_by_clients_async(transcripts)

        # Note: We do not persist LLM prompts/responses; only transcripts are cached for test speed.
        
        if not client_transcripts:
            print("⚠ No clients identified. This might mean:")
            print("   - All participants are internal team members")
            print("   - Check INTERNAL_DOMAINS in config")
            return
        
        print(f"✓ Identified {len(client_transcripts)} unique client(s):")
        for client_id, client_transcript_list in client_transcripts.items():
            print(f"   - {client_id}: {len(client_transcript_list)} meeting(s)")
        
        # Step 3: Format conversations
        print("\n[3/4] Formatting conversations...")
        for client_id, conversations in client_transcripts.items():
            formatted_text = data_processor.format_conversations(conversations)
            print(f"✓ Formatted text for {client_id} ({len(formatted_text)} characters)")
            # Show preview
            preview = formatted_text[:200] + "..." if len(formatted_text) > 200 else formatted_text
            print(f"   Preview: {preview}\n")
        
        # Step 4: Generate Word documents
        print("\n[4/4] Generating Word documents...")
        # Calculate date range for past week (same as Flow 1)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=7)
        date_range_str = f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
        print(f"Date range: {date_range_str}")
        
        word_generator = WordGenerator()
        generated_files = []
        
        for client_id, conversations in client_transcripts.items():
            formatted_text = data_processor.format_conversations(conversations)
            file_path = await word_generator.create_document(client_id, formatted_text, date_range=date_range_str)
            generated_files.append({
                "client": client_id,
                "file_path": file_path
            })
            print(f"✓ Generated: {file_path}")
        
        # Summary
        print("\n" + "=" * 80)
        print("PIPELINE TEST COMPLETE!")
        print("=" * 80)
        print(f"✓ Processed {len(transcripts)} transcript(s)")
        print(f"✓ Identified {len(client_transcripts)} client(s)")
        print(f"✓ Generated {len(generated_files)} Word document(s)")

        # Show per-client meeting counts
        print("\nPer-client meeting counts:")
        for client_id in sorted(client_transcripts.keys()):
            print(f"   - {client_id}: {len(client_transcripts[client_id])} meeting(s)")

        print("\nGenerated files:")
        for file_info in generated_files:
            client_id = file_info['client']
            count = len(client_transcripts.get(client_id, []))
            print(f"   - {client_id} ({count} meetings): {file_info['file_path']}")
        
    except Exception as e:
        print(f"\n{'=' * 80}")
        print("ERROR OCCURRED:")
        print(f"{'=' * 80}")
        print(f"Error type: {type(e).__name__}")
        print(f"Error message: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_full_pipeline())

