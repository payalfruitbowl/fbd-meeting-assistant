"""
Interactive test script for Agno agent with Pinecone knowledge base.

This script provides a real-time conversation interface in the terminal.
You can ask questions and the agent will search the knowledge base and respond.

Usage:
    python test_agno_agent.py
"""
import logging
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

from app.config import settings
from app.services.agno_agent import AgnoAgentService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main interactive conversation loop."""
    print("=" * 60)
    print("Agno Agent - Interactive Test")
    print("=" * 60)
    print("\nInitializing agent with Pinecone knowledge base...")
    
    # Verify environment variables
    if not os.getenv("PINECONE_API_KEY"):
        logger.error("PINECONE_API_KEY not found in environment variables")
        logger.error("Make sure .env file exists and contains PINECONE_API_KEY")
        return
    
    if not os.getenv("GROQ_API_KEY"):
        logger.error("GROQ_API_KEY not found in environment variables")
        logger.error("Make sure .env file exists and contains GROQ_API_KEY")
        return
    
    if not settings.PINECONE_INDEX_NAME:
        logger.error("PINECONE_INDEX_NAME not set in environment variables")
        return
    
    try:
        # Initialize Agno agent
        agent_service = AgnoAgentService(
            agent_name="Meeting Transcript Assistant",
            model_id="openai/gpt-oss-120b"  # Groq model
        )
        
        print(f"\n✓ Agent initialized successfully!")
        print(f"✓ Connected to Pinecone index: {settings.PINECONE_INDEX_NAME}")
        print(f"✓ Knowledge base ready (max_results: 50)")
        print("\n" + "=" * 60)
        print("Start asking questions! Type 'exit' or 'quit' to end.")
        print("=" * 60 + "\n")
        
        # Interactive conversation loop with session history
        session_id = "interactive_session"  # Use same session_id for conversation continuity
        print(f"Session ID: {session_id} (chat history enabled)\n")
        
        while True:
            try:
                # Get user input
                question = input("You: ").strip()
                
                # Check for exit commands
                if question.lower() in ['exit', 'quit', 'bye', 'q']:
                    print("\nGoodbye! 👋")
                    break
                
                # Skip empty questions
                if not question:
                    continue
                
                # Query the agent with session_id for chat history
                print("\n🤔 Thinking...")
                response = agent_service.query(question, session_id=session_id)
                
                # Display response
                print(f"\nAgent: {response}\n")
                print("-" * 60 + "\n")
                
            except KeyboardInterrupt:
                print("\n\nInterrupted. Goodbye! 👋")
                break
            except Exception as e:
                logger.error(f"Error processing query: {e}", exc_info=True)
                print(f"\n❌ Error: {str(e)}\n")
                print("-" * 60 + "\n")
    
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}", exc_info=True)
        print(f"\n❌ Failed to initialize agent: {str(e)}")
        print("Check your environment variables and Pinecone index configuration.")


if __name__ == "__main__":
    main()

