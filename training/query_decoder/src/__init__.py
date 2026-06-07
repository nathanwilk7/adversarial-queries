# ADVQ Soft Prompt Fine-tuning
# A framework for fine-tuning language models with embedding-based soft prompts

from .model import EmbeddingPromptFullModel
from .dataset import EmbeddingPromptDataset, embedding_aware_collate_for_transformer_decoder
from .recipe import EmbeddingFinetuneRecipe

__version__ = "0.1.0"
__all__ = [
    "EmbeddingPromptFullModel",
    "EmbeddingPromptDataset", 
    "embedding_aware_collate_for_transformer_decoder",
    "EmbeddingFinetuneRecipe",
]