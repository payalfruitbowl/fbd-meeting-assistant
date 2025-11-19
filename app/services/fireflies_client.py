"""
Fireflies API client for fetching transcripts.
Fireflies API uses GraphQL, not REST.
"""
import httpx
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
from app.config import settings

logger = logging.getLogger(__name__)


class FirefliesClient:
    """Client for interacting with Fireflies API (GraphQL)."""
    
    def __init__(self):
        self.api_key = settings.FIREFLIES_API_KEY
        # Fireflies base URL (hardcoded - safe)
        self.base_url = settings.FIREFLIES_API_BASE_URL
        # Fireflies GraphQL endpoint
        self.graphql_url = f"{self.base_url}/graphql"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def _execute_graphql_query(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute a GraphQL query against Fireflies API.
        
        Args:
            query: GraphQL query string
            variables: Optional variables for the query
            
        Returns:
            Response data dictionary
        """
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.graphql_url,
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            
            # Check for GraphQL errors
            if "errors" in result:
                error_messages = [err.get("message", str(err)) for err in result["errors"]]
                raise Exception(f"GraphQL errors: {', '.join(error_messages)}")
            
            return result.get("data", {})
    
    async def get_weekly_transcripts_list(self) -> List[Dict[str, Any]]:
        """
        Step 1: Fetch list of transcripts from the past week (basic info only).
        This gets transcript IDs which we'll use to fetch full details.
        
        Returns:
            List of transcript dictionaries with basic info (id, title, participants, etc.)
        """
        try:
            # Calculate date range for past week
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=7)
            
            # Format dates in ISO 8601 format: YYYY-MM-DDTHH:mm.sssZ
            from_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            to_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            logger.info(f"Fetching transcripts list from {start_date.date()} to {end_date.date()}")
            
            # GraphQL query to fetch transcripts list (based on official docs)
            query = """
            query GetTranscriptsList($fromDate: DateTime, $toDate: DateTime, $limit: Int) {
                transcripts(
                    fromDate: $fromDate
                    toDate: $toDate
                    limit: $limit
                ) {
                    id
                    title
                    date
                    dateString
                    duration
                    participants
                    organizer_email
                    host_email
                    meeting_attendees {
                        email
                        name
                        displayName
                    }
                    transcript_url
                }
            }
            """
            
            variables = {
                "fromDate": from_date_str,
                "toDate": to_date_str,
                "limit": 50  # Max 50 per query
            }
            
            data = await self._execute_graphql_query(query, variables)
            transcripts = data.get("transcripts", [])
            
            logger.info(f"Retrieved {len(transcripts)} transcript IDs")
            return transcripts
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching transcripts list: {e.response.status_code} - {e.response.text}")
            try:
                error_detail = e.response.json()
                logger.error(f"Error details: {error_detail}")
            except:
                logger.error(f"Error response text: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error fetching transcripts list: {str(e)}")
            raise
    
    async def get_weekly_transcripts(self) -> List[Dict[str, Any]]:
        """
        Fetch all transcripts from the past week with full details.
        This is a two-step process:
        1. Get list of transcripts (IDs)
        2. Fetch full details for each transcript
        
        Returns:
            List of complete transcript dictionaries
        """
        try:
            # Step 1: Get list of transcripts
            transcript_list = await self.get_weekly_transcripts_list()
            
            if not transcript_list:
                logger.info("No transcripts found for the past week")
                return []
            
            # Step 2: Fetch full details for each transcript
            full_transcripts = []
            for transcript_info in transcript_list:
                transcript_id = transcript_info.get("id")
                if transcript_id:
                    try:
                        full_transcript = await self.get_transcript_details(transcript_id)
                        # Merge basic info with full details
                        full_transcript.update(transcript_info)
                        full_transcripts.append(full_transcript)
                    except Exception as e:
                        logger.warning(f"Failed to fetch full transcript {transcript_id}: {str(e)}")
                        # Use basic info if full fetch fails
                        full_transcripts.append(transcript_info)
            
            logger.info(f"Retrieved {len(full_transcripts)} complete transcripts")
            return full_transcripts
            
        except Exception as e:
            logger.error(f"Error fetching weekly transcripts: {str(e)}")
            raise

    async def get_transcripts_list_between(self, from_date_iso: str, to_date_iso: str, limit: int = 50):
        """
        Fetch transcripts list between provided ISO datetimes (YYYY-MM-DDTHH:MM:SS.000Z).
        Returns basic info only (ids, title, participants, etc.).
        """
        try:
            query = """
            query GetTranscriptsList($fromDate: DateTime, $toDate: DateTime, $limit: Int) {
                transcripts(
                    fromDate: $fromDate
                    toDate: $toDate
                    limit: $limit
                ) {
                    id
                    title
                    date
                    dateString
                    duration
                    participants
                    organizer_email
                    host_email
                    meeting_attendees {
                        email
                        name
                        displayName
                    }
                    transcript_url
                }
            }
            """
            variables = {"fromDate": from_date_iso, "toDate": to_date_iso, "limit": limit}
            data = await self._execute_graphql_query(query, variables)
            transcripts = data.get("transcripts", [])
            logger.info(f"Retrieved {len(transcripts)} transcripts in range")
            return transcripts
        except Exception as e:
            logger.error(f"Error fetching transcripts in range: {str(e)}")
            raise
    
    async def get_transcript_details(self, transcript_id: str) -> Dict[str, Any]:
        """
        Step 2: Fetch complete transcript details by ID using GraphQL.
        Based on official Fireflies API docs.
        
        Args:
            transcript_id: The transcript ID
            
        Returns:
            Complete transcript dictionary with sentences and all details
        """
        try:
            # GraphQL query for complete transcript (based on official docs)
            query = """
            query GetTranscript($transcriptId: String!) {
                transcript(id: $transcriptId) {
                    id
                    title
                    date
                    dateString
                    duration
                    participants
                    organizer_email
                    host_email
                    meeting_attendees {
                        email
                        name
                        displayName
                    }
                    sentences {
                        index
                        speaker_name
                        speaker_id
                        text
                        raw_text
                        start_time
                        end_time
                    }
                    summary {
                        overview
                        action_items
                        keywords
                    }
                }
            }
            """
            
            variables = {"transcriptId": transcript_id}
            data = await self._execute_graphql_query(query, variables)
            
            return data.get("transcript", {})
                
        except Exception as e:
            logger.error(f"Error fetching transcript {transcript_id}: {str(e)}")
            raise

