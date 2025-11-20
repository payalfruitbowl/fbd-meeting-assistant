"""
Pinecone client service for index management and data operations.

This service handles:
- Index creation/deletion (using Pinecone SDK v5.4.2)
- Data upsert operations with FastEmbed embeddings
- Data deletion operations
- Index stats and checks

Note: Index creation/deletion should ideally be done via CLI, but this provides
programmatic access when needed.
"""
import logging
from typing import List, Dict, Any, Optional
from pinecone import Pinecone, ServerlessSpec
from fastembed import TextEmbedding

from app.config import settings

logger = logging.getLogger(__name__)


class PineconeClient:
    """
    Pinecone client for managing indexes and data operations.
    Uses FastEmbed for local embeddings (no API calls).
    Compatible with Pinecone v5.4.2 API.
    """
    
    def __init__(self):
        """Initialize Pinecone client and FastEmbed embedder."""
        if not settings.PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY must be set in environment variables")
        
        self.api_key = settings.PINECONE_API_KEY
        self.index_name = settings.PINECONE_INDEX_NAME
        self.dimension = settings.PINECONE_DIMENSION
        self.metric = settings.PINECONE_METRIC
        self.cloud = settings.PINECONE_CLOUD
        self.region = settings.PINECONE_REGION
        
        # Initialize Pinecone client (v5.4.2 API - new format)
        self.pc = Pinecone(api_key=self.api_key)
        
        # Initialize FastEmbed for local embeddings
        self.embedder = TextEmbedding(model_name=settings.FASTEMBED_MODEL)
        
        # Get index if it exists
        self.index = None
        if self.index_name:
            try:
                self.index = self.pc.Index(self.index_name)
                logger.info(f"Connected to Pinecone index: {self.index_name}")
            except Exception as e:
                logger.warning(f"Index {self.index_name} not found or not accessible: {e}")
    
    def create_index(self, index_name: Optional[str] = None) -> bool:
        """
        Create a serverless Pinecone index without integrated embeddings.
        Uses FastEmbed for local embeddings instead.
        
        Args:
            index_name: Name of the index (uses config default if not provided)
            
        Returns:
            True if index was created, False if it already exists
        """
        name = index_name or self.index_name
        if not name:
            raise ValueError("Index name must be provided or set in PINECONE_INDEX_NAME")
        
        # Check if index already exists (v5.4.2 API)
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        if name in existing_indexes:
            logger.info(f"Index {name} already exists")
            self.index = self.pc.Index(name)
            return False
        
        try:
            # Create serverless index (v5.4.2 API - new format)
            self.pc.create_index(
                name=name,
                dimension=self.dimension,
                metric=self.metric,
                spec=ServerlessSpec(
                    cloud=self.cloud,
                    region=self.region
                )
            )
            logger.info(f"Created Pinecone index: {name} (dimension={self.dimension}, metric={self.metric})")
            
            # Connect to the new index
            self.index = self.pc.Index(name)
            return True
        except Exception as e:
            logger.error(f"Failed to create index {name}: {e}")
            raise
    
    def delete_index(self, index_name: Optional[str] = None) -> bool:
        """
        Delete a Pinecone index.
        
        Args:
            index_name: Name of the index (uses config default if not provided)
            
        Returns:
            True if index was deleted, False if it didn't exist
        """
        name = index_name or self.index_name
        if not name:
            raise ValueError("Index name must be provided or set in PINECONE_INDEX_NAME")
        
        # Check if index exists (v5.4.2 API)
        existing_indexes = [idx.name for idx in self.pc.list_indexes()]
        if name not in existing_indexes:
            logger.info(f"Index {name} does not exist")
            return False
        
        try:
            self.pc.delete_index(name)
            logger.info(f"Deleted Pinecone index: {name}")
            if self.index_name == name:
                self.index = None
            return True
        except Exception as e:
            logger.error(f"Failed to delete index {name}: {e}")
            raise
    
    def get_embedding(self, text: str) -> List[float]:
        """
        Generate embedding for a single text using FastEmbed.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector as list of floats
        """
        # FastEmbed returns an iterator, get the first (and only) result
        embedding = list(self.embedder.embed([text]))[0]
        return embedding.tolist()
    
    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts using FastEmbed.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        embeddings = list(self.embedder.embed(texts))
        return [emb.tolist() for emb in embeddings]
    
    def upsert_vectors(
        self,
        vectors: List[Dict[str, Any]]
    ) -> None:
        """
        Upsert vectors to Pinecone index (uses default empty namespace).
        
        Args:
            vectors: List of vector dictionaries with format:
                {
                    "id": "unique_id",
                    "values": [0.1, 0.2, ...],  # embedding vector
                    "metadata": {"key": "value"}  # optional metadata
                }
        """
        if not self.index:
            raise ValueError("No index connected. Create or connect to an index first.")
        
        try:
            # Pinecone v5.4.2 upsert format (no namespace = default empty namespace)
            self.index.upsert(vectors=vectors)
            logger.info(f"Upserted {len(vectors)} vectors")
        except Exception as e:
            logger.error(f"Failed to upsert vectors: {e}")
            raise
    
    def upsert_texts(
        self,
        texts: List[Dict[str, Any]]
    ) -> None:
        """
        Upsert texts to Pinecone by generating embeddings with FastEmbed (uses default empty namespace).
        
        Args:
            texts: List of text dictionaries with format:
                {
                    "id": "unique_id",
                    "text": "text content to embed",
                    "metadata": {"key": "value"}  # optional metadata
                }
        """
        if not self.index:
            raise ValueError("No index connected. Create or connect to an index first.")
        
        # Extract text content for batch embedding
        text_contents = [item["text"] for item in texts]
        
        # Generate embeddings in batch
        embeddings = self.get_embeddings_batch(text_contents)
        
        # Prepare vectors for upsert
        vectors = []
        for i, item in enumerate(texts):
            vector = {
                "id": item["id"],
                "values": embeddings[i],
                "metadata": item.get("metadata", {})
            }
            vectors.append(vector)
        
        # Upsert vectors
        self.upsert_vectors(vectors)
    
    def delete_vectors(
        self,
        ids: List[str]
    ) -> None:
        """
        Delete vectors by IDs (uses default empty namespace).
        
        Args:
            ids: List of vector IDs to delete
        """
        if not self.index:
            raise ValueError("No index connected. Create or connect to an index first.")
        
        try:
            self.index.delete(ids=ids)
            logger.info(f"Deleted {len(ids)} vectors")
        except Exception as e:
            logger.error(f"Failed to delete vectors: {e}")
            raise
    
    def delete_by_filter(
        self,
        filter_dict: Dict[str, Any]
    ) -> None:
        """
        Delete vectors by metadata filter (uses default empty namespace).
        
        Args:
            filter_dict: Metadata filter (e.g., {"category": "docs"})
        """
        if not self.index:
            raise ValueError("No index connected. Create or connect to an index first.")
        
        try:
            self.index.delete(filter=filter_dict)
            logger.info(f"Deleted vectors matching filter {filter_dict}")
        except Exception as e:
            logger.error(f"Failed to delete by filter: {e}")
            raise
    
    def get_index_stats(self) -> Dict[str, Any]:
        """
        Get index statistics.
        
        Returns:
            Dictionary with index stats
        """
        if not self.index:
            raise ValueError("No index connected. Create or connect to an index first.")
        
        try:
            stats = self.index.describe_index_stats()
            return stats
        except Exception as e:
            logger.error(f"Failed to get index stats: {e}")
            raise
    
    def list_indexes(self) -> List[str]:
        """
        List all indexes in the Pinecone project.
        
        Returns:
            List of index names
        """
        try:
            # v5.4.2 API returns IndexList object, extract names
            indexes = self.pc.list_indexes()
            return [idx.name for idx in indexes]
        except Exception as e:
            logger.error(f"Failed to list indexes: {e}")
            raise
    
    def query(
        self,
        vector: List[float],
        top_k: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None,
        include_metadata: bool = True
    ) -> Dict[str, Any]:
        """
        Query the index with a vector.
        
        Args:
            vector: Query vector (embedding)
            top_k: Number of results to return
            filter_dict: Optional metadata filter
            include_metadata: Whether to include metadata in results
            
        Returns:
            Query results dictionary
        """
        if not self.index:
            raise ValueError("No index connected. Create or connect to an index first.")
        
        try:
            query_params = {
                "vector": vector,
                "top_k": top_k,
                "include_metadata": include_metadata
            }
            
            if filter_dict:
                query_params["filter"] = filter_dict
            
            results = self.index.query(**query_params)
            return results
        except Exception as e:
            logger.error(f"Failed to query index: {e}")
            raise

