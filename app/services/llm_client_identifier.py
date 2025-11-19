"""
LLM-based client identification using Groq and Agno Agent.
"""
import logging
import asyncio
from collections import defaultdict
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.reasoning import ReasoningTools
from app.config import settings

logger = logging.getLogger(__name__)


class MeetingClientAssignment(BaseModel):
    """Client assignment for a single meeting."""
    meeting_id: str = Field(description="The meeting/transcript ID")
    client_domain: str | None = Field(None, description="The identified client domain (e.g., 'everme.ai'). None if no client identified.")
    confidence: float | None = Field(None, description="Confidence score (free-form, not validated)")
    reasoning: str = Field(description="Brief explanation of why this domain was chosen as the client")


class BatchClientAssignments(BaseModel):
    """Batch of client assignments for all meetings (flat, non-batched mode)."""
    assignments: List[MeetingClientAssignment] = Field(description="List of client assignments for all meetings")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Analysis metadata and patterns identified")


class DomainBatchResult(BaseModel):
    """Result for a single seed-domain batch."""
    seed_domain: str
    assignments: List[MeetingClientAssignment]
    batch_level_reasoning: str | None = None


class TitleAssignment(BaseModel):
    """Assignment based on title analysis for domainless meetings."""
    meeting_id: str
    client_domain: str | None = Field(None, description="Known domain if confidently mapped from title to known domains")
    client_name: str | None = Field(None, description="Brand/client name inferred from title if no domain is available")
    confidence: float | None = Field(None, description="Confidence score (free-form)")
    reasoning: str = Field(description="Why this client/domain/name was chosen")


class BatchTitleAssignments(BaseModel):
    """Batch title-based assignments."""
    assignments: List[TitleAssignment]


class LLMClientIdentifier:
    """Uses LLM to identify client domains from meeting data."""
    
    def __init__(self):
        self.api_key = settings.GROQ_API_KEY
        
        self.agent = Agent(
            # Make outputs deterministic
            model=Groq(id="openai/gpt-oss-120b", api_key=self.api_key, temperature=0, top_p=1),
            output_schema=BatchClientAssignments,
            instructions="""You are a client identification specialist for a digital agency.

GOAL: Analyze meeting transcripts and identify the CLIENT domain for each meeting.

The CLIENT is the company/organization we are providing services to (the primary customer).
NOT vendors, partners, agencies, or consultants.

IDENTIFICATION STRATEGY:
1. Analyze the MEETING TITLES and title_brand hints to determine the client. Titles often contain the client name (e.g., "EverMe Team Sync" → everme.ai).
2. Look for patterns across meetings - if a domain appears consistently, it's likely the client.
3. Consider the organizer domain if it's external (not internal team).
4. If multiple external domains exist:
   - The one in the meeting title is likely the client
   - The one that appears most frequently across meetings is likely the client
   - The one with the most participants is likely the client
5. Exclude internal team domains (fruitbowldigital.com)
6. Exclude generic email providers (gmail.com, outlook.com, yahoo.com, hotmail.com, icloud.com, aol.com, protonmail.com)

OUTPUT REQUIREMENTS:
- For each meeting, provide: meeting_id, client_domain, confidence (0.0-1.0), reasoning
- Confidence should be high (0.8+) if domain appears in title or is clearly the client
- Confidence should be lower (0.5-0.7) if inferred from patterns
- Include metadata about patterns you identified across meetings

Be precise and consistent. If the same client domain appears in multiple meetings, 
assign the same domain to all related meetings."""
        )
    
    # ===== Domain-batched mode with parallel calls =====

    async def identify_clients_batched(self, meetings: List[Dict[str, Any]], internal_domains: set, max_concurrency: int = 4) -> Dict[str, MeetingClientAssignment]:
        """
        Build domain-centric batches and run LLM calls in parallel (up to max_concurrency).
        Resolve overlaps by choosing assignment with highest adjusted confidence.
        """
        domain_batches = self._build_domain_batches(meetings, internal_domains)
        # Log detailed batch composition
        try:
            summary = {k: len(v) for k, v in domain_batches.items()}
            logger.info(f"[LLM] Domain batches built (count={len(summary)}): {summary}")
            for seed_domain, ms in domain_batches.items():
                ids = [m.get("id") for m in ms]
                titles = [m.get("title", "Untitled") for m in ms]
                logger.info(f"[LLM] Batch seed={seed_domain} meetings={len(ms)} ids={ids}")
                logger.info(f"[LLM] Batch seed={seed_domain} titles_sample={titles[:3]}")
        except Exception:
            logger.warning("[LLM] Failed to log batch composition details")

        semaphore = asyncio.Semaphore(max_concurrency)
        total_batches = len(domain_batches)
        logger.info(f"[LLM] Processing {total_batches} domain batches with max_concurrency={max_concurrency}")

        async def run_one(seed_domain: str, batch_meetings: List[Dict[str, Any]]):
            async with semaphore:
                logger.info(f"[LLM] Acquired semaphore for batch seed={seed_domain} (running in parallel)")
                return await self._identify_clients_for_domain_batch_async(seed_domain, batch_meetings, internal_domains)

        tasks = [run_one(d, ms) for d, ms in domain_batches.items()]
        results: List[DomainBatchResult] = []
        if tasks:
            logger.info(f"[LLM] Starting {len(tasks)} parallel LLM calls (max {max_concurrency} concurrent)...")
            results = await asyncio.gather(*tasks, return_exceptions=False)
            logger.info(f"[LLM] All {len(results)} parallel LLM calls completed")

        # Combine per-meeting best assignment with tie-breaks
        best: Dict[str, MeetingClientAssignment] = {}
        candidates_by_meeting: Dict[str, List[MeetingClientAssignment]] = defaultdict(list)
        meeting_map = {m.get("id"): m for m in meetings}
        domain_freq: Dict[str, int] = defaultdict(int)
        for r in results:
            for a in r.assignments:
                if a.client_domain:
                    domain_freq[a.client_domain] += 1

        # Deterministic tie-breaking using lexicographic priority
        def label(domain: str | None) -> str:
            return (domain or "").split(".")[0].lower()

        for r in results:
            for a in r.assignments:
                mid = a.meeting_id
                if mid not in meeting_map:
                    continue
                # Track all candidates for diagnostics
                candidates_by_meeting[mid].append(a)
                m = meeting_map[mid]
                title = (m.get("title") or "").lower()
                organizer_email = m.get("organizer_email") or ""
                organizer_domain = organizer_email.split("@")[1].lower().strip() if "@" in organizer_email else ""

                d = a.client_domain or ""
                f_title = 1 if (label(d) and label(d) in title) else 0
                f_organizer = 1 if (d and organizer_domain == d) else 0
                f_freq = min(1, domain_freq.get(d, 0))
                score_tuple = (f_title, f_organizer, f_freq, d)

                prev = best.get(mid)
                if prev:
                    prev_d = prev.client_domain or ""
                    prev_tuple = (
                        1 if (label(prev_d) and label(prev_d) in title) else 0,
                        1 if (prev_d and organizer_domain == prev_d) else 0,
                        min(1, domain_freq.get(prev_d, 0)),
                        prev_d,
                    )
                else:
                    prev_tuple = (-1, -1, -1, "")

                if (not prev) or (score_tuple > prev_tuple):
                    best[mid] = MeetingClientAssignment(
                        meeting_id=a.meeting_id,
                        client_domain=a.client_domain,
                        confidence=a.confidence,  # retain original value for logs only
                        reasoning=a.reasoning,
                    )

        # Diagnostics: show meetings with multiple candidate domains and the chosen one
        try:
            for mid, cands in candidates_by_meeting.items():
                if len(cands) > 1:
                    chosen = best.get(mid)
                    cand_summary = [(c.client_domain, c.confidence) for c in cands]
                    logger.info(f"[LLM] Multi-candidate meeting {mid}: candidates={cand_summary} chosen={(chosen.client_domain if chosen else None, chosen.confidence if chosen else None)}")
        except Exception:
            logger.warning("[LLM] Failed to log multi-candidate diagnostics")

        logger.info(f"[LLM] Final per-meeting assignments: {len(best)} of {len(meetings)}")
        return best

    # ===== Helpers for batched mode =====

    def _extract_external_domains(self, meeting: Dict[str, Any], internal_domains: set) -> set:
        externals = set()
        participants = meeting.get("participants", [])
        for p in participants:
            if isinstance(p, str) and "@" in p:
                domain = p.split("@")[1].lower().strip()
                if domain and domain not in internal_domains and domain not in {
                    "gmail.com","outlook.com","hotmail.com","yahoo.com","icloud.com","aol.com","protonmail.com"
                }:
                    externals.add(domain)
        attendees = meeting.get("meeting_attendees", [])
        for a in attendees:
            if isinstance(a, dict):
                email = a.get("email","")
                if email and "@" in email:
                    domain = email.split("@")[1].lower().strip()
                    if domain and domain not in internal_domains and domain not in {
                        "gmail.com","outlook.com","hotmail.com","yahoo.com","icloud.com","aol.com","protonmail.com"
                    }:
                        externals.add(domain)
        for key in ("organizer_email","host_email"):
            email = meeting.get(key, "")
            if email and "@" in email:
                domain = email.split("@")[1].lower().strip()
                if domain and domain not in internal_domains and domain not in {
                    "gmail.com","outlook.com","hotmail.com","yahoo.com","icloud.com","aol.com","protonmail.com"
                }:
                    externals.add(domain)
        return externals

    def _build_domain_batches(self, meetings: List[Dict[str, Any]], internal_domains: set) -> Dict[str, List[Dict[str, Any]]]:
        domain_to_meetings: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for m in meetings:
            externals = self._extract_external_domains(m, internal_domains)
            for d in externals:
                domain_to_meetings[d].append(m)
        return dict(domain_to_meetings)

    def _create_domain_batch_prompt(self, seed_domain: str, context_items: List[Dict[str, Any]], internal_domains: set) -> str:
        prompt = f"""You are identifying the CLIENT for meetings that all include the domain: {seed_domain}

Client definition:
- The CLIENT is the company we work for (not a vendor/partner/agency).
- Use patterns across all meetings in this batch.

Exclude internal domains: {', '.join(sorted(internal_domains))}
Exclude generic providers: gmail.com, outlook.com, yahoo.com, hotmail.com, icloud.com, aol.com, protonmail.com

Important acronym hints:
- "FBD" means "Fruitbowl Digital" which is an internal team (not a client). Do NOT assign Fruitbowl/FBD as client.

Instructions:
- For EACH meeting below, decide the client domain by analyzing BOTH the title/title_brand and the external domains.
- If seed_domain appears to be the client, choose it.
- If another external domain is clearly the client (by title, organizer, or recurring presence), choose that.
- If truly ambiguous, set client_domain=null and explain briefly.

Return the structured output per this schema: DomainBatchResult(assignments=[MeetingClientAssignment(...)]).

Meetings in batch:
"""
        for i, c in enumerate(context_items, 1):
            prompt += f"""
--- Meeting {i} ---
ID: {c['meeting_id']}
Title: {c['title']}
Title brand: {c.get('title_brand','')}
External domains: {', '.join(c['external_domains']) if c['external_domains'] else 'none'}
Participant counts: {c.get('participant_count_by_domain', {})}
Organizer domain: {c.get('organizer_domain','')}
Host domain: {c.get('host_domain','')}
"""
        prompt += """

Decide client_domain for each meeting. Be consistent across the batch.
"""
        return prompt

    async def _identify_clients_for_domain_batch_async(self, seed_domain: str, meetings: List[Dict[str, Any]], internal_domains: set) -> DomainBatchResult:
        # Build context entries for this batch
        context_items = []
        def _brand_from_title(title: str) -> str | None:
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
        for m in meetings:
            externals = self._extract_external_domains(m, internal_domains)
            participant_count_by_domain = {}
            for p in m.get("participants", []):
                if isinstance(p, str) and "@" in p:
                    d = p.split("@")[1].lower().strip()
                    if d in externals:
                        participant_count_by_domain[d] = participant_count_by_domain.get(d, 0) + 1
            organizer_domain = ""
            if m.get("organizer_email") and "@" in m["organizer_email"]:
                organizer_domain = m["organizer_email"].split("@")[1].lower().strip()
            host_domain = ""
            if m.get("host_email") and "@" in m["host_email"]:
                host_domain = m["host_email"].split("@")[1].lower().strip()
            context_items.append({
                "meeting_id": m.get("id","unknown"),
                "title": m.get("title","Untitled"),
                "title_brand": _brand_from_title(m.get("title","")) or "",
                "external_domains": sorted(list(externals)),
                "participant_count_by_domain": participant_count_by_domain,
                "organizer_domain": organizer_domain,
                "host_domain": host_domain,
            })

        prompt = self._create_domain_batch_prompt(seed_domain, context_items, internal_domains)
        logger.info(f"[LLM] Starting batch seed={seed_domain} meetings={len(meetings)} prompt_chars={len(prompt)}")
        # Note: We do not persist prompts to disk to avoid unintended caching beyond API transcripts.
        # Run agent.run() in thread pool to allow parallel execution
        result = await asyncio.to_thread(self.agent.run, prompt)
        logger.info(f"[LLM] Completed batch seed={seed_domain}")

        content = getattr(result, "content", None)
        if content is None:
            logger.warning(f"[LLM] No content for seed={seed_domain}")
            return DomainBatchResult(seed_domain=seed_domain, assignments=[], batch_level_reasoning=None)

        def to_batch(content_obj) -> DomainBatchResult:
            if hasattr(content_obj, "model_dump"):
                data = content_obj.model_dump(exclude_none=True)
                # Allow content to be either DomainBatchResult-like or BatchClientAssignments-like
                if "seed_domain" in data:
                    return DomainBatchResult(**data)
                # Wrap if flat
                return DomainBatchResult(seed_domain=seed_domain, assignments=[MeetingClientAssignment(**a) for a in data.get("assignments", [])])
            if isinstance(content_obj, dict):
                if "seed_domain" in content_obj:
                    return DomainBatchResult(**content_obj)
                return DomainBatchResult(seed_domain=seed_domain, assignments=[MeetingClientAssignment(**a) for a in content_obj.get("assignments", [])])
            if isinstance(content_obj, str):
                import json
                parsed = json.loads(content_obj)
                if "seed_domain" in parsed:
                    return DomainBatchResult(**parsed)
                return DomainBatchResult(seed_domain=seed_domain, assignments=[MeetingClientAssignment(**a) for a in parsed.get("assignments", [])])
            raise ValueError("Unsupported LLM content type")

        try:
            parsed = to_batch(content)
            # Note: We do not persist LLM responses to disk to avoid unintended caching beyond API transcripts.
        except Exception as e:
            logger.warning(f"[LLM] Failed to parse batch response for seed={seed_domain}: {e}")
            return DomainBatchResult(seed_domain=seed_domain, assignments=[], batch_level_reasoning=None)

        logger.info(f"[LLM] Parsed batch seed={seed_domain} assignments={len(parsed.assignments)}")
        return parsed

    # ===== Title-based mapping for domainless meetings =====

    async def identify_clients_from_titles(
        self,
        meetings: List[Dict[str, Any]],
        target_client: str = None,
        known_domains: List[str] = None,
        internal_domains: set = None,
    ) -> Dict[str, TitleAssignment]:
        """
        For meetings with no external domains, use titles to infer client.
        - If target_client is provided (Option 3): Look for that specific client only
        - If target_client is None (Option 1): Identify all clients generically
        """
        if not meetings:
            return {}
        
        if known_domains is None:
            known_domains = []
        if internal_domains is None:
            internal_domains = set()

        # Build context
        def _brand_from_title(title: str) -> str | None:
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

        context_items = []
        for m in meetings:
            title = m.get("title", "") or ""
            org_val = m.get("organizer_email") or ""
            host_val = m.get("host_email") or ""
            context_items.append({
                "meeting_id": m.get("id", "unknown"),
                "title": title,
                "title_brand": _brand_from_title(title) or "",
                "organizer_domain": (org_val.split("@")[1].lower().strip()
                                     if "@" in org_val else ""),
                "host_domain": (host_val.split("@")[1].lower().strip()
                                if "@" in host_val else ""),
            })

        # Build prompt - different based on whether we're looking for a specific client or all clients
        if target_client:
            # Option 3: Looking for specific client
            prompt = f"""You are identifying if meetings belong to a SPECIFIC CLIENT: "{target_client}"

These meetings have NO external domains, so we analyze titles to determine if they belong to "{target_client}".

Rules:
- Analyze the title and title_brand to see if they indicate "{target_client}".
- If the title clearly indicates "{target_client}" (e.g., "Croffle Guys x Fruitbowl", "EverMe Team Sync", "everme weekly standup"), set client_name="{target_client}" (or client_domain if you know it).
- If the title does NOT indicate "{target_client}", return nulls (do not assign).
- Do NOT output dates/times or "Untitled" or internal-only references like "Fruitbowl" as client_name.
- If unsure, return nulls.

Important acronym hints:
- "FBD" means "Fruitbowl Digital" (internal team). Do NOT assign as client.

Separator rule for two-sided titles (like "X x Y", "X <> Y"):
- If one side is internal (e.g., "FBD") and the other side looks like "{target_client}", prefer the non-internal side as client_name.
- If both sides are unclear, return nulls.

Output: BatchTitleAssignments(assignments=[TitleAssignment(...)])
"""
        else:
            # Option 1: Identify all clients generically
            prompt = f"""You are identifying CLIENTS from MEETING TITLES for meetings that have NO external domains.

Rules:
- Analyze the title and title_brand to determine the client.
- If you can confidently map the brand to a domain (from week context you infer), set client_domain.
- If no domain is available but the title clearly indicates a proper company brand (e.g., "Croffle Guys", "HME"), set client_name and leave client_domain null.
- Do NOT output dates/times or "Untitled" or internal-only references like "Fruitbowl" as client_name.
- If unsure, return nulls.

Important acronym hints:
- "FBD" means "Fruitbowl Digital" which is an internal team (not a client). If title contains "FBD", treat it as internal context, not a client.

Separator rule for two-sided titles (like "X x Y", "X <> Y"):
- If one side is internal (e.g., "FBD") and the other side looks like a company/brand, prefer the non-internal side as client_name.
- If both sides are unclear brands, return nulls (do not guess).

Output: BatchTitleAssignments(assignments=[TitleAssignment(...)])
"""
        prompt += "\nMeetings:\n"
        for i, c in enumerate(context_items, 1):
            prompt += f"""
--- Meeting {i} ---
ID: {c['meeting_id']}
Title: {c['title']}
Title brand: {c['title_brand']}
Organizer domain: {c['organizer_domain']}
Host domain: {c['host_domain']}
"""
        prompt += "\nReturn structured output only.\n"

        # Use a temporary agent with title schema
        temp_agent = Agent(
            model=Groq(id="moonshotai/kimi-k2-instruct-0905", api_key=self.api_key, temperature=0, top_p=1),
            output_schema=BatchTitleAssignments,
            instructions="Extract clients from titles as per rules. Be conservative; return nulls if unsure.",
        )

        logger.info(f"[LLM-TITLE] Starting title-based batch for {len(meetings)} domainless meetings")
        result = await asyncio.to_thread(temp_agent.run, prompt)
        content = getattr(result, "content", None)
        if content is None:
            logger.warning("[LLM-TITLE] No content returned")
            return {}

        def to_batch(content_obj) -> BatchTitleAssignments:
            if hasattr(content_obj, "model_dump"):
                data = content_obj.model_dump(exclude_none=True)
                return BatchTitleAssignments(**data)
            if isinstance(content_obj, dict):
                return BatchTitleAssignments(**content_obj)
            if isinstance(content_obj, str):
                import json
                parsed = json.loads(content_obj)
                return BatchTitleAssignments(**parsed)
            raise ValueError("Unsupported LLM content type for title-based mapping")

        try:
            parsed = to_batch(content)
        except Exception as e:
            logger.warning(f"[LLM-TITLE] Failed to parse title-based response: {e}")
            return {}

        out: Dict[str, TitleAssignment] = {}
        for a in parsed.assignments:
            out[a.meeting_id] = a
            logger.info(f"[LLM-TITLE] {a.meeting_id}: domain={a.client_domain} name={a.client_name} conf={a.confidence} reason={a.reasoning}")
        return out

