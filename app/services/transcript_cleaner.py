"""
Transcript cleaning service.

Cleans and optimizes transcript text by merging consecutive messages
from the same speaker to reduce redundancy and improve readability.
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class TranscriptCleaner:
    """
    Service to clean and optimize transcript text.
    Merges consecutive messages from the same speaker.
    """
    
    @staticmethod
    def clean_transcript_sentences(sentences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Clean transcript sentences by merging consecutive same-speaker messages.
        
        Args:
            sentences: List of sentence dictionaries from Fireflies API
            
        Returns:
            List of cleaned sentence dictionaries with merged consecutive messages
        """
        if not sentences:
            return []
        
        cleaned = []
        current_speaker = None
        current_text_parts = []
        current_sentence = None
        
        for sentence in sentences:
            speaker_id = sentence.get("speaker_id")
            speaker_name = sentence.get("speaker_name", "Unknown Speaker")
            text = sentence.get("text", sentence.get("raw_text", "")).strip()
            
            if not text:
                continue
            
            # If same speaker as previous, merge the text
            if speaker_id == current_speaker and current_sentence:
                # Merge: add text to current sentence
                current_text_parts.append(text)
                # Update the text in current sentence
                current_sentence["text"] = " ".join(current_text_parts)
                if "raw_text" in current_sentence:
                    current_sentence["raw_text"] = " ".join(current_text_parts)
            else:
                # New speaker or first sentence - save previous and start new
                if current_sentence:
                    cleaned.append(current_sentence)
                
                # Start new sentence
                current_speaker = speaker_id
                current_text_parts = [text]
                current_sentence = sentence.copy()
                # Ensure text fields are set
                current_sentence["text"] = text
                if "raw_text" not in current_sentence:
                    current_sentence["raw_text"] = text
        
        # Don't forget the last sentence
        if current_sentence:
            cleaned.append(current_sentence)
        
        logger.debug(f"Merged {len(sentences)} sentences into {len(cleaned)} cleaned sentences")
        return cleaned
    
    @staticmethod
    def clean_transcript(transcript: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean a full transcript by merging consecutive same-speaker messages.
        
        Args:
            transcript: Full transcript dictionary from Fireflies API
            
        Returns:
            Cleaned transcript dictionary with merged sentences
        """
        if "sentences" not in transcript or not transcript["sentences"]:
            return transcript
        
        # Create a copy to avoid modifying original
        cleaned_transcript = transcript.copy()
        
        # Clean the sentences
        cleaned_sentences = TranscriptCleaner.clean_transcript_sentences(
            transcript["sentences"]
        )
        
        cleaned_transcript["sentences"] = cleaned_sentences
        
        return cleaned_transcript
    
    @staticmethod
    def format_cleaned_transcript_text(transcript: Dict[str, Any]) -> str:
        """
        Extract and format cleaned transcript text.
        Uses cleaned sentences (merged consecutive same-speaker messages).
        
        Args:
            transcript: Transcript dictionary (can be cleaned or raw)
            
        Returns:
            Formatted text string with merged messages
        """
        if "sentences" in transcript and transcript["sentences"]:
            lines = []
            for sentence in transcript["sentences"]:
                speaker = sentence.get("speaker_name", "Unknown Speaker")
                text = sentence.get("text", sentence.get("raw_text", ""))
                if text.strip():
                    lines.append(f"{speaker}: {text}")
            return "\n".join(lines)
        return ""

