"""
Query VAE 256 - Grammar-Constrained Query Generation

This module provides inference capabilities for generating grammar-constrained
query specifications from 256-dimensional embeddings.
"""

from .grammar_constrained_inference import (
    GrammarConstrainedInference,
    EmbeddingMapper,
)

__all__ = [
    "GrammarConstrainedInference",
    "EmbeddingMapper",
]
