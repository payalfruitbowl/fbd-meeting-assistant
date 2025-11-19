"""
Data processing module for filtering and formatting transcripts.
"""
import logging
import asyncio
from typing import List, Dict, Any, Set
from collections import defaultdict
from app.config import settings
from app.services.llm_client_identifier import LLMClientIdentifier
import re

logger = logging.getLogger(__name__)


class DataProcessor:
    """Processes and formats transcript data."""
    
    def __init__(self):
        # Parse internal domains and emails from config
        self.internal_domains = set(
            domain.strip().lower() 
            for domain in settings.INTERNAL_DOMAINS.split(",") 
            if domain.strip()
        )
        self.internal_emails = set(
            email.strip().lower() 
            for email in settings.INTERNAL_EMAILS.split(",") 
            if email.strip()
        )
        
        # Initialize LLM client identifier
        self.llm_identifier = LLMClientIdentifier()
        logger.info("LLM client identification initialized")
        
    def _brand_from_title(self, title: str) -> str | None:
        if not title:
            return None
        t = title.strip()
        for sep in [" x ", " X ", " <> ", " | ", " – ", " - "]:
            if sep in t:
                left, right = t.split(sep, 1)
                if "fruitbowl" in left.lower():
                    return right.strip().split(":")[0]
                return left.strip().split(":")[0]
        return t.split(":")[0].strip()

    def _map_brand_to_domain(self, brand: str, week_domains: set[str]) -> str | None:
        if not brand:
            return None
        b = brand.lower().replace(" ", "").replace("-", "")
        for d in week_domains:
            if b == d.split(".")[0].lower().replace("-", ""):
                return d
        for d in week_domains:
            if d.split(".")[0].lower() in brand.lower():
                return d
        return None

    
    def _is_internal_team(self, email: str) -> bool:
        """
        Check if an email belongs to internal team.
        
        Args:
            email: Email address to check
            
        Returns:
            True if internal team member, False otherwise
        """
        if not email:
            return False
        
        email_lower = email.lower().strip()
        
        # Check if email is in internal emails list
        if email_lower in self.internal_emails:
            return True
        
        # Check if email domain is in internal domains
        if "@" in email_lower:
            domain = email_lower.split("@")[1]
            if domain in self.internal_domains:
                return True
        
        return False
    
    def _extract_client_emails(self, transcript: Dict[str, Any]) -> List[str]:
        """
        Extract client emails from transcript (excluding internal team).
        
        Args:
            transcript: Single transcript dictionary
            
        Returns:
            List of client email addresses
        """
        client_emails = []
        
        # Check participants (array of email strings)
        participants = transcript.get("participants", [])
        if isinstance(participants, list):
            for participant in participants:
                if isinstance(participant, str):
                    email = participant
                elif isinstance(participant, dict):
                    email = participant.get("email", "")
                else:
                    continue
                
                if email and not self._is_internal_team(email):
                    client_emails.append(email.lower())
        
        # Check meeting_attendees (array of objects with email)
        meeting_attendees = transcript.get("meeting_attendees", [])
        if isinstance(meeting_attendees, list):
            for attendee in meeting_attendees:
                if isinstance(attendee, dict):
                    email = attendee.get("email", "")
                    if email and not self._is_internal_team(email):
                        email_lower = email.lower()
                        if email_lower not in client_emails:
                            client_emails.append(email_lower)
        
        return client_emails
    
    def _get_client_identifier(self, client_emails: List[str]) -> str:
        """
        Generate a client identifier from email list.
        Strategy: Use email prefix (part before @) for all external emails.
        This works for both generic providers (gmail, outlook) and custom domains.
        
        Examples:
        - safaee.gr@gmail.com → "safaee.gr"
        - dany@everme.ai → "dany"
        - lukas@lifeengineer.ai → "lukas"
        
        Args:
            client_emails: List of client email addresses
            
        Returns:
            Client identifier string
        """
        if not client_emails:
            return "Unknown Client"
        
        # If single client, use email prefix
        if len(client_emails) == 1:
            email = client_emails[0]
            if "@" in email:
                # Extract prefix (part before @) and clean it up
                prefix = email.split("@")[0]
                # Capitalize first letter for readability
                return prefix.title() if prefix else "Unknown Client"
            return email
        
        # Multiple clients - use first client's prefix + " and others"
        first_email = client_emails[0]
        if "@" in first_email:
            prefix = first_email.split("@")[0]
            base_name = prefix.title() if prefix else "Client"
            return f"{base_name} and {len(client_emails) - 1} others"
        
        return f"{len(client_emails)} Clients"
    
    def _normalize_label(self, s: str) -> str:
        return re.sub(r"[\W_]+", "", (s or "").lower()).strip()

    def _title_brand(self, title: str) -> str:
        t = (title or "").strip()
        for sep in [" x ", " X ", " <> ", " | ", " – ", " - "]:
            if sep in t:
                left, right = t.split(sep, 1)
                if "fruitbowl" in left.lower():
                    return right.strip().split(":")[0]
                return left.strip().split(":")[0]
        return t.split(":")[0].strip()

    async def filter_for_client_async(self, transcripts: List[Dict[str, Any]], client_query: str, use_llm: bool = True) -> List[Dict[str, Any]]:
        """
        Keep only meetings that match provided client string as:
        - domain (e.g., 'everme.ai'), or
        - brand label (e.g., 'EverMe', 'Croffle Guys') via title/title_brand.
        If use_llm is True, domainless meetings go through title-based LLM and only those matching the client brand are kept.
        """
        if not transcripts:
            return []

        query = (client_query or "").strip()
        query_lower = query.lower()

        def externals_of(m: Dict[str, Any]) -> Set[str]:
            try:
                return self.llm_identifier._extract_external_domains(m, self.internal_domains)
            except Exception:
                return set()

        kept: List[Dict[str, Any]] = []
        
        logger.info(f"[FILTER-STEP1] Starting direct search (grep-style) for client '{query}' in {len(transcripts)} transcripts")

        # Step 1: Direct search (grep-style) - simple string matching
        step1_matches = 0
        for m in transcripts:
            transcript_id = m.get("id", "unknown")
            title = (m.get("title", "") or "").lower()
            externals = externals_of(m)
            organizer = (m.get("organizer_email") or "").lower()
            host = (m.get("host_email") or "").lower()
            
            # Extract domains from organizer/host
            org_dom = organizer.split("@")[1] if "@" in organizer else ""
            host_dom = host.split("@")[1] if "@" in host else ""
            
            match_reason = None
            
            # Direct search: query appears in title OR matches any external domain OR organizer/host domain
            if query_lower in title:
                match_reason = f"title contains '{query}'"
                kept.append(m)
                step1_matches += 1
                logger.info(f"[FILTER-STEP1] ✓ {transcript_id}: MATCHED - {match_reason} | Title: '{m.get('title', 'N/A')}'")
                continue
            
            # Check if query matches any external domain (exact or partial)
            for ext_domain in externals:
                if query_lower in ext_domain.lower() or ext_domain.lower() in query_lower:
                    match_reason = f"external domain '{ext_domain}' matches '{query}'"
                    kept.append(m)
                    step1_matches += 1
                    logger.info(f"[FILTER-STEP1] ✓ {transcript_id}: MATCHED - {match_reason} | Title: '{m.get('title', 'N/A')}' | Domains: {list(externals)}")
                    break
            
            if match_reason:
                continue
            
            # Check organizer/host domains
            if org_dom and (query_lower in org_dom or org_dom in query_lower):
                match_reason = f"organizer domain '{org_dom}' matches '{query}'"
                kept.append(m)
                step1_matches += 1
                logger.info(f"[FILTER-STEP1] ✓ {transcript_id}: MATCHED - {match_reason} | Title: '{m.get('title', 'N/A')}'")
                continue
            if host_dom and (query_lower in host_dom or host_dom in query_lower):
                match_reason = f"host domain '{host_dom}' matches '{query}'"
                kept.append(m)
                step1_matches += 1
                logger.info(f"[FILTER-STEP1] ✓ {transcript_id}: MATCHED - {match_reason} | Title: '{m.get('title', 'N/A')}'")
                continue
            
            # No match in Step 1
            if externals:
                logger.debug(f"[FILTER-STEP1] ✗ {transcript_id}: No match | Title: '{m.get('title', 'N/A')}' | Has external domains: {list(externals)}")
            else:
                logger.debug(f"[FILTER-STEP1] ✗ {transcript_id}: No match | Title: '{m.get('title', 'N/A')}' | No external domains (will go to Step 2 if use_llm=True)")
        
        logger.info(f"[FILTER-STEP1] Step 1 complete: {step1_matches} matches found out of {len(transcripts)} transcripts")

        # Step 2: LLM pass (only for domainless meetings NOT already matched)
        step2_matches = 0
        if use_llm:
            remaining: List[Dict[str, Any]] = []
            already_ids = {m.get("id") for m in kept}
            for m in transcripts:
                if m.get("id") in already_ids:
                    continue
                if externals_of(m):
                    continue  # Skip meetings with external domains (they should have been caught in Step 1)
                remaining.append(m)

            if remaining:
                logger.info(f"[FILTER-STEP2] Starting LLM analysis for {len(remaining)} domainless meetings (target client: '{query}')")
                # Pass the target client query to LLM
                title_map = await self.llm_identifier.identify_clients_from_titles(
                    meetings=remaining,
                    target_client=query,  # Tell LLM what we're looking for
                    known_domains=[],
                    internal_domains=self.internal_domains,
                )
                for m in remaining:
                    transcript_id = m.get("id", "unknown")
                    ta = title_map.get(transcript_id)
                    if not ta:
                        continue
                    # Check if LLM identified this specific client
                    if ta.client_name and query_lower in ta.client_name.lower():
                        kept.append(m)
                        step2_matches += 1
                        logger.info(f"[FILTER-STEP2] ✓ {transcript_id}: MATCHED via LLM - client_name='{ta.client_name}' | Title: '{m.get('title', 'N/A')}'")
                    elif ta.client_domain and query_lower in ta.client_domain.lower():
                        kept.append(m)
                        step2_matches += 1
                        logger.info(f"[FILTER-STEP2] ✓ {transcript_id}: MATCHED via LLM - client_domain='{ta.client_domain}' | Title: '{m.get('title', 'N/A')}'")
                logger.info(f"[FILTER-STEP2] Step 2 complete: {step2_matches} additional matches found")
            else:
                logger.info(f"[FILTER-STEP2] No domainless meetings to analyze (all were matched in Step 1 or have external domains)")
        else:
            logger.info(f"[FILTER-STEP2] Skipped (use_llm=False)")

        logger.info(f"[FILTER-SUMMARY] Total matches: {len(kept)} (Step 1: {step1_matches}, Step 2: {step2_matches})")
        return kept

    async def filter_by_clients_async(self, transcripts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Filter transcripts by unique clients using domain-batched LLM identification.
        
        Args:
            transcripts: List of transcript dictionaries from Fireflies API
            
        Returns:
            Dictionary mapping client identifiers to their transcripts
        """
        if not transcripts:
            return {}
        
        logger.info(f"Using LLM (domain-batched) to identify clients for {len(transcripts)} meetings...")
        # Run domain-batched identification with parallel LLM calls (concurrency=4)
        client_assignments = await self.llm_identifier.identify_clients_batched(
            meetings=transcripts,
            internal_domains=self.internal_domains,
            max_concurrency=4,
        )
        
        # Group transcripts by client domain (LLM decisions only for meetings with domains)
        client_transcripts = defaultdict(list)
        for transcript in transcripts:
            transcript_id = transcript.get("id")
            assignment = client_assignments.get(transcript_id)
            if assignment and assignment.client_domain:
                client_domain = assignment.client_domain
                client_name = client_domain.split(".")[0].title()
                client_transcripts[client_name].append(transcript)
                logger.info(f"[ASSIGN] {transcript_id} → {client_name} (conf={assignment.confidence:.2f})")
            else:
                logger.warning(f"[ASSIGN] No client for {transcript_id} title='{transcript.get('title','N/A')}' (skipped)")

        # Pass 2: Title-based mapping for meetings with no external domains
        # Build list of domainless transcripts not yet assigned
        domainless: List[Dict[str, Any]] = []
        known_domains = set()
        for t in transcripts:
            try:
                for d in self.llm_identifier._extract_external_domains(t, self.internal_domains):
                    known_domains.add(d)
            except Exception:
                pass
        assigned_ids = set(client_assignments.keys())
        for t in transcripts:
            tid = t.get("id")
            # consider only those with no LLM assignment and no externals
            if tid in assigned_ids and client_assignments[tid] and client_assignments[tid].client_domain:
                continue
            try:
                externals = self.llm_identifier._extract_external_domains(t, self.internal_domains)
            except Exception:
                externals = set()
            if not externals:
                domainless.append(t)

        if domainless:
            logger.info(f"[ASSIGN-TITLE] Running title-based mapping for {len(domainless)} domainless meetings")
            title_map = await self.llm_identifier.identify_clients_from_titles(
                meetings=domainless,
                target_client=None,  # Option 1: identify all clients, not a specific one
                known_domains=list(known_domains),
                internal_domains=self.internal_domains,
            )
            # Acceptance rules
            allow_brand = settings.INCLUDE_BRAND_ONLY
            for t in domainless:
                tid = t.get("id")
                ta = title_map.get(tid)
                if not ta:
                    continue
                if ta.client_domain:
                    cname = ta.client_domain.split(".")[0].title()
                    client_transcripts[cname].append(t)
                    logger.info(f"[ASSIGN-TITLE] {tid} → {cname} via title-domain (conf={ta.confidence})")
                elif allow_brand and ta.client_name:
                    # Deterministic acceptance for brand-only when enabled
                    cname = ta.client_name.title()
                    client_transcripts[cname].append(t)
                    logger.info(f"[ASSIGN-TITLE] {tid} → {cname} via title-brand (accepted; confidence ignored)")
                else:
                    logger.info(f"[ASSIGN-TITLE] {tid} no accepted title-based mapping (allow_brand={allow_brand}, conf={ta.confidence})")
        # Optional ambiguous bucket for remaining unassigned
        if settings.INCLUDE_AMBIGUOUS_BUCKET:
            assigned_set = {t.get("id") for cl in client_transcripts.values() for t in cl}
            for t in transcripts:
                tid = t.get("id")
                if tid in assigned_set:
                    continue
                title = (t.get("title") or "").strip()
                if not title or title.lower().startswith("untitled"):
                    continue
                # Avoid internal-only obvious patterns
                if "fruitbowl" in title.lower():
                    continue
                bucket = title.split(":")[0].strip()
                if not bucket:
                    continue
                client_transcripts[bucket].append(t)
                logger.info(f"[ASSIGN-AMBIGUOUS] {tid} → {bucket} (exact-title bucket)")
        
        logger.info(f"Filtered {len(transcripts)} transcripts into {len(client_transcripts)} unique clients")
        for client_id, client_transcript_list in client_transcripts.items():
            logger.info(f"  - {client_id}: {len(client_transcript_list)} meeting(s)")
        
        return dict(client_transcripts)

    def format_conversations(self, conversations: List[Dict[str, Any]]) -> str:
        """
        Format conversations into simple text format.
        
        Args:
            conversations: List of transcript dictionaries for a client
            
        Returns:
            Formatted text string
        """
        formatted_text = ""
        
        for conversation in conversations:
            # Add meeting header
            meeting_title = conversation.get("title", "Untitled Meeting")
            meeting_date = conversation.get("dateString", conversation.get("date", ""))
            
            formatted_text += f"\n{'='*60}\n"
            formatted_text += f"Meeting: {meeting_title}\n"
            formatted_text += f"Date: {meeting_date}\n"
            formatted_text += f"{'='*60}\n\n"
            
            # Format transcript content
            transcript_content = self._extract_transcript_content(conversation)
            formatted_text += transcript_content
            formatted_text += "\n\n"
        
        return formatted_text.strip()
    
    def _format_time(self, seconds: float) -> str:
        """
        Format time in seconds to readable format (MM:SS or HH:MM:SS).
        
        Args:
            seconds: Time in seconds
            
        Returns:
            Formatted time string
        """
        try:
            total_seconds = int(seconds)
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            secs = total_seconds % 60
            
            if hours > 0:
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            else:
                return f"{minutes:02d}:{secs:02d}"
        except (ValueError, TypeError):
            return ""
    
    def _extract_transcript_content(self, transcript: Dict[str, Any]) -> str:
        """
        Extract and format transcript content into readable conversation format.
        Format: Speaker Name: text [start_time - end_time]
        Or: Speaker Name: text (if no time available)
        
        Args:
            transcript: Single transcript dictionary
            
        Returns:
            Formatted conversation text in natural readable format
        """
        formatted_content = ""
        
        # Check for sentences array (from complete transcript query)
        if "sentences" in transcript and transcript["sentences"]:
            for sentence in transcript["sentences"]:
                speaker = sentence.get("speaker_name", "Unknown Speaker")
                text = sentence.get("text", sentence.get("raw_text", ""))
                start_time = sentence.get("start_time")
                end_time = sentence.get("end_time")
                
                if not text.strip():
                    continue
                
                # Format: Speaker Name: text [00:00 - 00:05]
                line = f"{speaker}: {text}"
                
                # Add time range if available
                if start_time is not None or end_time is not None:
                    time_parts = []
                    if start_time is not None:
                        start_str = self._format_time(start_time)
                        if start_str:
                            time_parts.append(start_str)
                    if end_time is not None:
                        end_str = self._format_time(end_time)
                        if end_str:
                            time_parts.append(end_str)
                    
                    if time_parts:
                        if len(time_parts) == 2:
                            time_range = f"[{time_parts[0]} - {time_parts[1]}]"
                        else:
                            time_range = f"[{time_parts[0]}]"
                        line += f" {time_range}"
                
                formatted_content += line + "\n"
        
        if not formatted_content:
            logger.warning(f"No transcript content found for transcript {transcript.get('id', 'unknown')}")
            formatted_content = "[Transcript content not available for this meeting]"
        
        return formatted_content

