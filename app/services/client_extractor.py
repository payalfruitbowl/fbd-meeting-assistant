"""
Production client extraction service.

Extracts all external client domains from meeting transcripts
and returns them as a list for metadata storage.
"""
import logging
from typing import List, Dict, Any
from app.services.data_processor import DataProcessor

logger = logging.getLogger(__name__)


class ClientExtractor:
    """
    Extracts client identifiers from meeting transcripts.
    Returns a list of all external clients found.
    """
    
    def __init__(self, data_processor: DataProcessor):
        """
        Initialize client extractor.
        
        Args:
            data_processor: DataProcessor instance for internal domain checking
        """
        self.data_processor = data_processor
        
        # Generic email providers to exclude (not considered client domains)
        self.generic_providers = {
            "gmail.com", "outlook.com", "yahoo.com", "hotmail.com", 
            "icloud.com", "aol.com", "protonmail.com", "mail.com",
            "live.com", "msn.com", "ymail.com"
        }
    
    def extract_clients(self, transcript: Dict[str, Any]) -> List[str]:
        """
        Identify ALL clients from transcript by extracting external domains from participant emails.
        Returns a list of client identifiers (domain names without TLD, capitalized).
        
        Strategy:
        1. First try to extract client from title (if title contains client name)
        2. Extract ALL external domains from participant emails (excluding internal and generic providers)
        3. Return list of all external client domains found
        
        Args:
            transcript: Transcript dictionary from Fireflies API
            
        Returns:
            List of client identifiers (e.g., ["EverMe", "KingStreetMedia"])
        """
        clients = []
        
        # Step 1: Try to extract client from title first
        title = transcript.get("title", "")
        if title and not title.lower().startswith("untitled"):
            brand = self.data_processor._brand_from_title(title)
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
                if self.data_processor._is_internal_team(email):
                    continue
                # Skip generic email providers
                if domain in self.generic_providers:
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
                client_name = domain_name.title()
                if client_name not in clients:
                    clients.append(client_name)
        
        # If no clients found, return empty list (will be stored as empty list in metadata)
        # This allows the agent to still find these meetings via semantic search
        return clients

