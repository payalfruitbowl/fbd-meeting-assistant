"""
Configuration settings for the application.
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Fireflies API Configuration
    # Base URL is hardcoded as it's safe (not sensitive)
    FIREFLIES_API_BASE_URL: str = "https://api.fireflies.ai"
    # Only API key comes from environment (sensitive)
    FIREFLIES_API_KEY: str
    
    # Groq API Configuration
    GROQ_API_KEY: str
    
    # Pinecone Configuration
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_NAME: Optional[str] = None
    PINECONE_DIMENSION: int = 384  # Default for FastEmbed BAAI/bge-small-en-v1.5
    PINECONE_METRIC: str = "cosine"  # cosine, dotproduct, euclidean
    PINECONE_CLOUD: str = "aws"  # aws, gcp, azure
    PINECONE_REGION: str = "us-east-1"
    
    # FastEmbed Configuration
    FASTEMBED_MODEL: str = "BAAI/bge-small-en-v1.5"  # Default FastEmbed model
    
    # Client Identification Configuration
    # Internal team domains to exclude (comma-separated)
    INTERNAL_DOMAINS: str = "fruitbowldigital.com"
    # Internal team emails to exclude (comma-separated, optional)
    INTERNAL_EMAILS: str = ""
    # Allow grouping by brand-only (title-derived) when no domain is available
    INCLUDE_BRAND_ONLY: bool = True
    # Minimum confidence for brand-only grouping (0.0-1.0 scale from LLM)
    BRAND_ONLY_MIN_CONFIDENCE: float = 0.7
    # If still unassigned after LLM passes, place into an ambiguous bucket using the exact meeting title
    INCLUDE_AMBIGUOUS_BUCKET: bool = True
    
    # Output Configuration
    OUTPUT_DIR: str = "./output"
    
    # Application Configuration
    APP_NAME: str = "Fireflies Transcript Processor"
    DEBUG: bool = False
    
    # CORS Configuration
    # Comma-separated list of allowed origins (e.g., "http://localhost:3000,https://your-frontend.onrender.com")
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,https://fbd-meeting-assistant-frontend.onrender.com"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Create global settings instance
settings = Settings()

# Ensure output directory exists
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)

