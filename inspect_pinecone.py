"""
Script to inspect what's currently in Pinecone index.
Shows date ranges, sample records, and statistics.

Usage:
    python inspect_pinecone.py
"""
import logging
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

from app.config import settings
from app.services.pinecone_client import PineconeClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def inspect_pinecone():
    """Inspect what's in Pinecone index."""
    logger.info("=" * 60)
    logger.info("Pinecone Index Inspection")
    logger.info("=" * 60)
    
    # Initialize Pinecone client
    pinecone_client = PineconeClient()
    
    if not pinecone_client.index:
        logger.error("No index connected!")
        return
    
    # 1. Get index stats
    logger.info("\n1. INDEX STATISTICS:")
    logger.info("-" * 60)
    try:
        stats = pinecone_client.get_index_stats()
        total_vectors = stats.get('total_vector_count', 0)
        logger.info(f"Total vectors in index: {total_vectors:,}")
        
        if 'namespaces' in stats:
            logger.info(f"Namespaces: {list(stats['namespaces'].keys())}")
            for ns, ns_stats in stats['namespaces'].items():
                logger.info(f"  Namespace '{ns}': {ns_stats.get('vector_count', 0):,} vectors")
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return
    
    if total_vectors == 0:
        logger.warning("Index is empty - no vectors found!")
        return
    
    # 2. Query by date ranges to analyze what's actually in Pinecone
    logger.info("\n2. QUERYING BY DATE RANGES:")
    logger.info("-" * 60)
    
    try:
        # Create a dummy query vector (all zeros) - needed for query but we'll filter by date
        dummy_vector = [0.0] * pinecone_client.dimension
        
        # Query different date ranges to see what exists
        all_dates = []
        date_to_count = defaultdict(int)
        sample_records = []
        total_queried = 0
        
        # Query by year ranges to see what data exists
        today = datetime.utcnow()
        year_ranges = []
        
        # Check last 3 years
        for year_offset in range(0, 3):
            year = today.year - year_offset
            start_date = datetime(year, 1, 1)
            end_date = datetime(year, 12, 31, 23, 59, 59)
            year_ranges.append((year, start_date, end_date))
        
        logger.info("Querying by year ranges to see what data exists...")
        
        for year, start_date, end_date in year_ranges:
            start_timestamp = int(start_date.timestamp())
            end_timestamp = int(end_date.timestamp())
            
            try:
                # Query with date filter - just need a few records to see if data exists
                filter_dict = {
                    "date_timestamp": {
                        "$gte": start_timestamp,
                        "$lte": end_timestamp
                    }
                }
                
                results = pinecone_client.query(
                    vector=dummy_vector,
                    top_k=100,  # Get up to 100 records per year
                    filter_dict=filter_dict,
                    include_metadata=True
                )
                
                matches = results.get('matches', [])
                if matches:
                    logger.info(f"  {year}: Found {len(matches)} records (showing first {min(10, len(matches))})")
                    total_queried += len(matches)
                    
                    for match in matches:
                        metadata = match.get('metadata', {})
                        date_str = metadata.get('date', '')
                        date_timestamp = metadata.get('date_timestamp')
                        
                        if date_str:
                            # Normalize date string
                            if 'T' in date_str:
                                date_str = date_str.split('T')[0]
                            all_dates.append(date_str)
                            date_to_count[date_str] += 1
                        
                        # Store first 10 records as samples
                        if len(sample_records) < 10:
                            sample_records.append({
                                'id': match.get('id', ''),
                                'date': date_str,
                                'date_timestamp': date_timestamp,
                                'title': metadata.get('title', 'N/A'),
                                'client': metadata.get('client', []),
                                'meeting_id': metadata.get('meeting_id', ''),
                            })
                else:
                    logger.info(f"  {year}: No records found")
                    
            except Exception as e:
                logger.warning(f"  {year}: Query failed - {e}")
        
        logger.info(f"\nTotal records queried: {total_queried}")
        
        # 3. Analyze date ranges
        logger.info("\n3. DATE RANGE ANALYSIS:")
        logger.info("-" * 60)
        
        if all_dates:
            # Parse dates and find min/max
            parsed_dates = []
            for date_str in all_dates:
                try:
                    if 'T' in date_str:
                        date_str = date_str.split('T')[0]
                    parsed_date = datetime.strptime(date_str, "%Y-%m-%d")
                    parsed_dates.append(parsed_date)
                except:
                    pass
            
            if parsed_dates:
                min_date = min(parsed_dates)
                max_date = max(parsed_dates)
                logger.info(f"Earliest date found: {min_date.strftime('%Y-%m-%d')}")
                logger.info(f"Latest date found: {max_date.strftime('%Y-%m-%d')}")
                logger.info(f"Date range span: {(max_date - min_date).days} days")
                
                # Count by year/month
                year_month_count = defaultdict(int)
                for date_str in all_dates:
                    if 'T' in date_str:
                        date_str = date_str.split('T')[0]
                    try:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        year_month = date_obj.strftime("%Y-%m")
                        year_month_count[year_month] += date_to_count[date_str]
                    except:
                        pass
                
                logger.info("\nRecords by Year-Month:")
                for ym in sorted(year_month_count.keys()):
                    logger.info(f"  {ym}: {year_month_count[ym]:,} records")
                
                # Check what would be deleted by current cleanup logic - query directly!
                logger.info(f"\n⚠️  CLEANUP ANALYSIS:")
                today = datetime.utcnow()
                cutoff_date = today.replace(year=today.year - 1)  # 1 year ago
                cutoff_timestamp = int(cutoff_date.timestamp())
                
                logger.info(f"Cleanup cutoff date: {cutoff_date.strftime('%Y-%m-%d')} (timestamp: {cutoff_timestamp})")
                logger.info("Querying records that would be deleted...")
                
                try:
                    # Query records older than cutoff
                    filter_dict_old = {
                        "date_timestamp": {"$lt": cutoff_timestamp}
                    }
                    
                    results_old = pinecone_client.query(
                        vector=dummy_vector,
                        top_k=1000,  # Get up to 1000 to estimate
                        filter_dict=filter_dict_old,
                        include_metadata=True
                    )
                    
                    old_records_count = len(results_old.get('matches', []))
                    logger.info(f"Records older than cutoff (sampled): {old_records_count}")
                    
                    if old_records_count > 0:
                        logger.warning(f"⚠️  These records would be DELETED by cleanup!")
                        logger.info(f"Records older than cutoff (sampled): {old_records_count:,}")
                        
                        # Also query what would remain
                        try:
                            filter_dict_new = {
                                "date_timestamp": {"$gte": cutoff_timestamp}
                            }
                            
                            results_new = pinecone_client.query(
                                vector=dummy_vector,
                                top_k=100,  # Just to verify
                                filter_dict=filter_dict_new,
                                include_metadata=True
                            )
                            
                            new_records_count = len(results_new.get('matches', []))
                            logger.info(f"Records newer than cutoff (sampled): {new_records_count:,}")
                            logger.info(f"Total vectors: {total_vectors:,}")
                            logger.info(f"Estimated to be deleted: {old_records_count:,}+ (may be more)")
                            logger.info(f"Estimated to remain: ~{total_vectors - old_records_count:,}")
                        except Exception as e:
                            logger.warning(f"Could not query new records: {e}")
                    else:
                        logger.info("✓ No records found older than cutoff - safe to run cleanup")
                        
                except Exception as e:
                    logger.warning(f"Failed to query old records: {e}")
                    
                    # Fallback: estimate from sampled data
                    records_before_cutoff = 0
                    for date_str, count in date_to_count.items():
                        try:
                            if 'T' in date_str:
                                date_str = date_str.split('T')[0]
                            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                            if date_obj.timestamp() < cutoff_timestamp:
                                records_before_cutoff += count
                        except:
                            pass
                    
                    if total_queried > 0:
                        estimated_before_cutoff = int((records_before_cutoff / total_queried) * total_vectors)
                        estimated_after_cutoff = total_vectors - estimated_before_cutoff
                        logger.info(f"Estimated records that would be deleted: ~{estimated_before_cutoff:,}")
                        logger.info(f"Estimated records that would remain: ~{estimated_after_cutoff:,}")
            else:
                logger.warning("Could not parse dates from metadata")
        else:
            logger.warning("No dates found in sampled records")
        
        # 4. Show sample records
        logger.info("\n4. SAMPLE RECORDS (first 10):")
        logger.info("-" * 60)
        for i, record in enumerate(sample_records, 1):
            logger.info(f"\nRecord {i}:")
            logger.info(f"  ID: {record['id']}")
            logger.info(f"  Meeting ID: {record['meeting_id']}")
            logger.info(f"  Date: {record['date']}")
            logger.info(f"  Date Timestamp: {record['date_timestamp']}")
            logger.info(f"  Title: {record['title']}")
            logger.info(f"  Clients: {record['client']}")
        
        # 5. Summary
        logger.info("\n" + "=" * 60)
        logger.info("SUMMARY:")
        logger.info("=" * 60)
        logger.info(f"Total vectors in index: {total_vectors:,}")
        logger.info(f"Records sampled: {total_queried:,}")
        if all_dates:
            logger.info(f"Unique dates found: {len(set(all_dates))}")
        
    except Exception as e:
        logger.error(f"Error during inspection: {e}", exc_info=True)
    
    logger.info("\n" + "=" * 60)
    logger.info("Inspection complete!")
    logger.info("=" * 60)


if __name__ == "__main__":
    # Verify environment variables
    import os
    if not os.getenv("PINECONE_API_KEY"):
        logger.error("PINECONE_API_KEY not found in environment variables")
        exit(1)
    
    if not os.getenv("PINECONE_INDEX_NAME"):
        logger.error("PINECONE_INDEX_NAME not found in environment variables")
        exit(1)
    
    inspect_pinecone()

