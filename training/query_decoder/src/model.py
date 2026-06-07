"""
Embedding Prompt Full Model - A wrapper for embedding-prompted fine-tuning.

This module provides the EmbeddingPromptFullModel class which wraps a base
transformer model and adds a trainable mapping FFN to convert input embeddings
into soft prompt tokens.
"""

import torch
from torch import nn
from typing import Optional


class EmbeddingPromptFullModel(nn.Module):
    """
    Wrapper for embedding-prompted full model fine-tuning with a trainable mapping FFN.
    Uses multiple tokens to encode the input embedding instead of 1.
    
    Args:
        base_model: The base transformer model to wrap
        input_embedding_dim: Dimension of input embeddings (e.g., 256 for text-embedding-3-large @ 256 dims)
        tokenizer: Optional tokenizer for decoding during debugging
        ffn_hidden_dim: Hidden dimension for the mapping FFN (default: 2x input_embedding_dim)
        num_embedding_tokens: Number of tokens to use for encoding the embedding (default: 4)
    """
    
    def __init__(
        self, 
        base_model: nn.Module, 
        input_embedding_dim: int, 
        tokenizer=None, 
        ffn_hidden_dim: Optional[int] = None, 
        num_embedding_tokens: int = 4
    ):
        super().__init__()
        self.base_model = base_model
        self.input_embedding_dim = input_embedding_dim
        self.tokenizer = tokenizer
        self.num_embedding_tokens = num_embedding_tokens
        
        # Get model dtype and hidden dimension
        model_dtype = next(base_model.parameters()).dtype
        self.model_dtype = model_dtype
        self.hidden_dim = base_model.tok_embeddings.embedding_dim
        
        # FFN hidden dimension (default to 2x input dim or can be configured)
        self.ffn_hidden_dim = ffn_hidden_dim or (input_embedding_dim * 2)
        
        # Track dimensions for later initialization
        self.has_initialized_mapping = False
        
        print(f"Model dtype: {model_dtype}, Hidden dim: {self.hidden_dim}, "
              f"Input dim: {input_embedding_dim}, FFN hidden: {self.ffn_hidden_dim}, "
              f"Embedding tokens: {self.num_embedding_tokens}")
        
        # Ensure all parameters are marked as requiring gradients
        for param in self.base_model.parameters():
            param.requires_grad = True
            
    def materialize_mapping_layer(self, device: torch.device) -> None:
        """
        Create and materialize the mapping FFN on the specified device.
        
        Args:
            device: The device to create the mapping layer on
        """
        if not hasattr(self, 'mapping_ffn') or not self.has_initialized_mapping:
            # Create a 3-layer FFN that outputs num_embedding_tokens * hidden_dim
            output_dim = self.num_embedding_tokens * self.hidden_dim
            self.mapping_ffn = nn.Sequential(
                nn.Linear(self.input_embedding_dim, self.ffn_hidden_dim, 
                         device=device, dtype=self.model_dtype),
                nn.GELU(),
                nn.Linear(self.ffn_hidden_dim, self.ffn_hidden_dim, 
                         device=device, dtype=self.model_dtype),
                nn.GELU(),
                nn.Linear(self.ffn_hidden_dim, output_dim, 
                         device=device, dtype=self.model_dtype)
            )
            
            # Initialize weights
            for layer in self.mapping_ffn:
                if isinstance(layer, nn.Linear):
                    nn.init.normal_(layer.weight, std=0.02)
                    nn.init.zeros_(layer.bias)
                    
            self.has_initialized_mapping = True
            print(f"Mapping FFN materialized on {device} with dtype {self.model_dtype} "
                  f"(output: {self.num_embedding_tokens} tokens)")

    def initialize_mapping_layer(self, device: Optional[torch.device] = None) -> None:
        """
        Initialize the mapping FFN on the specified device.
        
        Args:
            device: The device to initialize the mapping layer on
        """
        if device is not None:
            output_dim = self.num_embedding_tokens * self.hidden_dim
            real_mapping_ffn = nn.Sequential(
                nn.Linear(self.input_embedding_dim, self.ffn_hidden_dim, 
                         device=device, dtype=self.model_dtype),
                nn.GELU(),
                nn.Linear(self.ffn_hidden_dim, self.ffn_hidden_dim, 
                         device=device, dtype=self.model_dtype),
                nn.GELU(),
                nn.Linear(self.ffn_hidden_dim, output_dim, 
                         device=device, dtype=self.model_dtype)
            )
            
            # Initialize weights
            for layer in real_mapping_ffn:
                if isinstance(layer, nn.Linear):
                    nn.init.normal_(layer.weight, std=0.02)
                    nn.init.zeros_(layer.bias)
            
            self.mapping_ffn = real_mapping_ffn
            print(f"Mapping FFN initialized on {device} with dtype {self.model_dtype} "
                  f"(output: {self.num_embedding_tokens} tokens)")
    
    def forward(
        self, 
        input_embedding: torch.Tensor, 
        input_ids: torch.Tensor, 
        mask: torch.Tensor, 
        insert_pos: Optional[torch.Tensor] = None, 
        **kwargs
    ) -> torch.Tensor:
        """
        Forward method with embedding input handling using the mapping FFN.
        Inserts embedding tokens at the specified position.
        
        Args:
            input_embedding: Input embeddings of shape [batch_size, embed_dim]
            input_ids: Token IDs of shape [batch_size, seq_len]
            mask: Attention mask of shape [batch_size, seq_len]
            insert_pos: Position(s) to insert embeddings (default: position 1 after BOS)
            
        Returns:
            Output logits of shape [batch_size, seq_len, vocab_size]
        """
        # Ensure inputs have correct dtype
        input_embedding = input_embedding.to(self.model_dtype)
        
        # Map embedding to model's hidden dimension using the FFN
        # [batch_size, embed_dim] -> [batch_size, num_embedding_tokens * hidden_dim]
        mapped_flat = self.mapping_ffn(input_embedding)
        
        # Reshape to [batch_size, num_embedding_tokens, hidden_dim]
        batch_size = input_embedding.size(0)
        mapped_embedding = mapped_flat.view(batch_size, self.num_embedding_tokens, self.hidden_dim)
        
        # Get token embeddings from base model
        token_embeds = self.base_model.tok_embeddings(input_ids)
        
        # Get batch size and prepare for insertion
        seq_len = input_ids.size(1)
        
        # Handle insert_pos, ensuring it's a tensor with one position per batch item
        if insert_pos is None:
            positions = torch.ones(batch_size, dtype=torch.long, device=input_ids.device)
        elif isinstance(insert_pos, int):
            positions = torch.ones(batch_size, dtype=torch.long, device=input_ids.device) * insert_pos
        elif isinstance(insert_pos, torch.Tensor) and insert_pos.dim() == 0:
            positions = torch.ones(batch_size, dtype=torch.long, device=input_ids.device) * insert_pos.item()
        else:
            positions = insert_pos.to(input_ids.device)

        # Add validation/clamping for positions
        positions = torch.clamp(positions, 0, seq_len)
            
        # Prepare combined embeddings for each batch item
        combined_embeds_list = []
        combined_mask_list = []

        for i in range(batch_size):
            pos = positions[i].item()

            # Handle Embeddings
            current_embeds = token_embeds[i:i+1, :, :]
            prefix_embeds = current_embeds[:, :pos, :]
            rest_embeds = current_embeds[:, pos:, :]
            current_mapped_embedding = mapped_embedding[i:i+1]

            combined_embed = torch.cat([prefix_embeds, current_mapped_embedding, rest_embeds], dim=1)
            combined_embeds_list.append(combined_embed)

            # Handle Mask
            current_mask = mask[i:i+1, :]
            prefix_mask = current_mask[:, :pos]
            rest_mask = current_mask[:, pos:]

            embed_mask = torch.ones((1, self.num_embedding_tokens), dtype=torch.bool, device=mask.device)
            combined_mask = torch.cat([prefix_mask, embed_mask, rest_mask], dim=1)
            combined_mask_list.append(combined_mask)

        # Stack results
        combined_embeds = torch.cat(combined_embeds_list, dim=0)
        final_mask = torch.cat(combined_mask_list, dim=0)

        # Process through model layers with 3D mask
        h = combined_embeds
        hidden_states = []
        seq_len_plus_embed = h.shape[1]
        device = h.device

        # Create the 3D attention mask
        upper_tri_mask = torch.ones(
            (seq_len_plus_embed, seq_len_plus_embed), device=device, dtype=torch.bool
        ).triu(diagonal=1)
        causal_mask = ~upper_tri_mask
        padding_mask_expanded = final_mask[:, None, :]
        attn_mask = padding_mask_expanded & causal_mask

        for i, layer in enumerate(self.base_model.layers):
            if i in self.base_model.output_hidden_states:
                hidden_states.append(h)

            try:
                h = layer(h, mask=attn_mask)
            except TypeError:
                try:
                    h = layer(h, attn_mask=attn_mask)
                except TypeError as e:
                    print(f"ERROR: Layer {i} forward signature incompatible. Error: {e}")
                    raise

        if len(self.base_model.layers) in self.base_model.output_hidden_states:
            hidden_states.append(h)
        
        h = self.base_model.norm(h)
        output_intermediate = self.base_model.output(h)

        # Remove the embedding token positions from output
        final_output_list = []
        for i in range(batch_size):
            pos = torch.clamp(positions[i], 0, seq_len).item()

            prefix_logits = output_intermediate[i:i+1, :pos]
            rest_logits = output_intermediate[i:i+1, pos+self.num_embedding_tokens:]
            final_output_list.append(torch.cat([prefix_logits, rest_logits], dim=1))

        output = torch.cat(final_output_list, dim=0)

        return output if not hidden_states else [*hidden_states, output]
        
    def get_mapping_layer_state_dict(self) -> dict:
        """
        Get the state dict for just the mapping FFN.
        
        Returns:
            Dictionary containing mapping layer configuration and weights
        """
        return {
            "input_embedding_dim": self.input_embedding_dim,
            "hidden_dim": self.hidden_dim,
            "ffn_hidden_dim": self.ffn_hidden_dim,
            "num_embedding_tokens": self.num_embedding_tokens,
            "mapping_ffn": self.mapping_ffn.state_dict(),
            "model_dtype": str(self.model_dtype)
        }