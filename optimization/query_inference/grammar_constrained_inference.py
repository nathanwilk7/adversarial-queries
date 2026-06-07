"""Grammar-constrained inference using a fine-tuned LLM with vLLM backend.
Loads grammars from the grammars/ registry and uses OpenAI embeddings for encoding.
"""

import logging
import torch
import base64
import io
import numpy as np
import os
import json
from datetime import datetime
from openai import OpenAI
from transformers import AutoModelForCausalLM, AutoTokenizer
from typing import Union, List, Optional
from concurrent.futures import ThreadPoolExecutor

# Import grammar registry
from grammars import get_grammar_config

logger = logging.getLogger(__name__)


class EmbeddingMapper(torch.nn.Module):
    """Updated wrapper for the embedding mapping layer that matches new training architecture.
    Now outputs 4 tokens instead of 1."""
    def __init__(self, input_dim, hidden_dim, ffn_hidden_dim, num_embedding_tokens=4):
        super().__init__()
        self.num_embedding_tokens = num_embedding_tokens
        
        # Create the same 3-layer FFN as in training that outputs num_embedding_tokens * hidden_dim
        output_dim = num_embedding_tokens * hidden_dim
        self.mapping_ffn = torch.nn.Sequential(
            torch.nn.Linear(input_dim, ffn_hidden_dim),
            torch.nn.GELU(),
            torch.nn.Linear(ffn_hidden_dim, ffn_hidden_dim),
            torch.nn.GELU(),
            torch.nn.Linear(ffn_hidden_dim, output_dim)
        )
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.ffn_hidden_dim = ffn_hidden_dim
        
    def forward(self, x):
        """Map input embedding to model's hidden dimension and reshape to 4 tokens."""
        # x shape: [embedding_dim]
        batch_size = x.shape[0] if x.dim() > 1 else 1
        if x.dim() == 1:
            x = x.unsqueeze(0)  # Add batch dimension if needed
            
        # Map through FFN: [batch_size, embedding_dim] -> [batch_size, num_embedding_tokens * hidden_dim]
        mapped_flat = self.mapping_ffn(x)
        
        # Reshape to: [batch_size, num_embedding_tokens, hidden_dim]
        mapped_tokens = mapped_flat.view(batch_size, self.num_embedding_tokens, self.hidden_dim)
        
        return mapped_tokens


class GrammarConstrainedInference:
    """
    Grammar-constrained inference using a trained VAE model.
    
    This class handles:
    - Loading grammar from the central registry
    - Loading model and mapping layer weights
    - Generating grammar-constrained outputs from embeddings
    - Batch generation with concurrent API calls
    - Converting strings to embeddings
    """
    
    def __init__(self, 
                 grammar_name: str,
                 model_path: Optional[str] = None, 
                 mapping_layer_path: Optional[str] = None,
                 api_base_url: str = "http://localhost:8000/v1",
                 api_model_name: Optional[str] = None):
        """
        Initialize the inference class.
        
        Args:
            grammar_name: Name of grammar from registry (e.g., "imdb_full_21table", "sqlstorm")
            model_path: Path to the model directory (loaded on CPU). If None, uses registry config.
            mapping_layer_path: Path to the mapping layer weights. If None, uses registry config.
            api_base_url: Base URL for the hosted model API
            api_model_name: Model name for the API. If None, uses registry config.
        """
        self.device = torch.device("cpu")  # Force CPU to save VRAM
        self.api_base_url = api_base_url
        
        # Load grammar configuration from registry
        self.grammar_config = get_grammar_config(grammar_name)
        self.grammar = self.grammar_config.get_grammar()
        self.grammar_name = grammar_name
        
        logger.info(f"Loaded grammar: {grammar_name}")
        logger.info(f"  Schema: {self.grammar_config.schema}")
        logger.info(f"  Tables: {self.grammar_config.num_tables}")
        logger.info(f"  Description: {self.grammar_config.description}")
        
        # Use provided paths or fall back to registry config
        self.model_path = model_path or self.grammar_config.model_path
        self.mapping_layer_path = mapping_layer_path or self.grammar_config.mapping_layer_path
        self.model_name = api_model_name or self.grammar_config.api_model_name
        
        if self.model_path is None:
            raise ValueError(f"No model_path provided and none configured in registry for '{grammar_name}'")
        if self.mapping_layer_path is None:
            raise ValueError(f"No mapping_layer_path provided and none configured in registry for '{grammar_name}'")
        if self.model_name is None:
            raise ValueError(f"No api_model_name provided and none configured in registry for '{grammar_name}'")
        
        logger.info(f"Loading model from: {self.model_path}")
        logger.info(f"Loading mapping layer from: {self.mapping_layer_path}")
        logger.info(f"API model name: {self.model_name}")

        logger.info("Loading model and tokenizer on CPU")
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path, 
            torch_dtype=torch.float32,  # Use float32 for CPU
            device_map="cpu"
        )
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self.model.eval()
        
        logger.info("Loading mapping layer")
        state_dict = torch.load(self.mapping_layer_path, map_location=self.device, weights_only=False)
        
        # Create mapper with correct dimensions using new architecture
        self.num_embedding_tokens = state_dict.get('num_embedding_tokens', 4)  # Default to 4 if not in state dict
        self.mapper = EmbeddingMapper(
            input_dim=state_dict['input_embedding_dim'], 
            hidden_dim=state_dict['hidden_dim'],
            ffn_hidden_dim=state_dict['ffn_hidden_dim'],
            num_embedding_tokens=self.num_embedding_tokens
        )
        
        logger.info(f"Using {self.num_embedding_tokens} embedding tokens")
        
        # Load the mapping_ffn state dict (not mapping_layer)
        self.mapper.mapping_ffn.load_state_dict(state_dict['mapping_ffn'])
        self.mapper.to(self.device).to(torch.float32)
        self.mapper.eval()
        
        # Get token embeddings layer
        self.token_embeddings_layer = self.model.get_input_embeddings()
        
        # Define system message and tokens
        self.system_message = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nYou are a helpful assistant outputting SQL join specifications for a given join embedding.<|eot_id|>"
        self.sql_spec_prefix = "<|start_header_id|>embedding<|end_header_id|>\n\n"
        self.sql_spec_suffix = "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        
        # Pre-compute prefix and suffix embeddings
        self._prepare_embeddings()
        
        # Initialize OpenAI client
        self.client = OpenAI(
            api_key="EMPTY",
            base_url=api_base_url,
        )

        self.embedding_client = OpenAI()
        
        # Initialize LLM response logging
        self.llm_log_dir = None
        self.llm_log_counter = 0
        self.llm_logging_enabled = False
        
        logger.info("Inference engine ready")
    
    def enable_llm_logging(self, log_dir: str = None):
        """
        Enable logging of all LLM responses to files.
        
        Args:
            log_dir: Directory to save LLM responses. If None, uses 
                     '../lolbo_scripts/llm_responses/<timestamp>' relative to this file.
        """
        if log_dir is None:
            # Default to lolbo_scripts/llm_responses/<timestamp>
            script_dir = os.path.dirname(os.path.abspath(__file__))
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_dir = os.path.join(script_dir, '..', 'lolbo_scripts', 'llm_responses', timestamp)
        
        os.makedirs(log_dir, exist_ok=True)
        self.llm_log_dir = log_dir
        self.llm_log_counter = 0
        self.llm_logging_enabled = True
        logger.info(f"[LLM LOGGING] Enabled. Saving responses to: {log_dir}")
        return self
    
    def disable_llm_logging(self):
        """Disable LLM response logging."""
        self.llm_logging_enabled = False
        logger.info("[LLM LOGGING] Disabled.")
        return self
    
    def _log_llm_response(self, embedding_vector, generated_text: str, metadata: dict = None):
        """
        Log a single LLM response to file.
        
        Args:
            embedding_vector: The input embedding used for generation
            generated_text: The generated output text
            metadata: Additional metadata to log
        """
        if not self.llm_logging_enabled or self.llm_log_dir is None:
            return
        
        self.llm_log_counter += 1
        log_entry = {
            'id': self.llm_log_counter,
            'timestamp': datetime.now().isoformat(),
            'generated_text': generated_text,
            'embedding_stats': {
                'shape': list(embedding_vector.shape) if hasattr(embedding_vector, 'shape') else None,
                'min': float(np.min(embedding_vector)) if embedding_vector is not None else None,
                'max': float(np.max(embedding_vector)) if embedding_vector is not None else None,
                'mean': float(np.mean(embedding_vector)) if embedding_vector is not None else None,
            },
            'metadata': metadata or {}
        }
        
        # Save to individual JSON file
        log_file = os.path.join(self.llm_log_dir, f"response_{self.llm_log_counter:06d}.json")
        with open(log_file, 'w') as f:
            json.dump(log_entry, f, indent=2)
        
        combined_log = os.path.join(self.llm_log_dir, 'all_responses.jsonl')
        with open(combined_log, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
        
    def _prepare_embeddings(self):
        """Pre-compute prefix and suffix embeddings."""
        logger.debug("Preparing prefix and suffix embeddings")
        
        # Tokenize prefix and suffix
        prefix_tokens = self.tokenizer(
            self.system_message + self.sql_spec_prefix, 
            return_tensors="pt"
        ).to(self.device)
        
        suffix_tokens = self.tokenizer(
            self.sql_spec_suffix, 
            return_tensors="pt"
        ).to(self.device)
        
        # Get embeddings for tokens
        with torch.no_grad():
            self.prefix_embedding = self.token_embeddings_layer(prefix_tokens['input_ids'])
            self.suffix_embedding = self.token_embeddings_layer(suffix_tokens['input_ids'])
    
    def _encode_embeddings(self, embeddings):
        """Encode embeddings to base64 for API transmission."""
        buffer = io.BytesIO()
        torch.save(embeddings, buffer)
        buffer.seek(0)
        binary_data = buffer.read()
        return base64.b64encode(binary_data).decode("utf-8")
    
    def generate_with_grammar(self, 
                            embedding_vector, 
                            grammar: Optional[str] = None, 
                            max_tokens: int = 128, 
                            temperature: float = 0.7) -> Optional[str]:
        """
        Generate output from embedding vector with grammar constraints.
        
        Args:
            embedding_vector: 256-dimensional input vector (numpy array or list)
            grammar: Optional grammar override. If None, uses the grammar from registry.
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            
        Returns:
            Generated text string, or None on error
        """
        # Use instance grammar if not overridden
        if grammar is None:
            grammar = self.grammar

        # Convert embedding to tensor
        if not isinstance(embedding_vector, torch.Tensor):
            embed_tensor = torch.tensor(embedding_vector).to(self.device).to(torch.float32)
        else:
            embed_tensor = embedding_vector.to(self.device).to(torch.float32)
        
        # Map embedding to model's hidden dimension and get multiple tokens
        # embed_tensor shape: [embedding_dim] -> mapped_embed shape: [1, num_embedding_tokens, hidden_dim]
        mapped_embed = self.mapper(embed_tensor)
        
        # Combine embeddings: prefix + mapped_embedding (now 4 tokens) + suffix
        combined_embeds = torch.cat([
            self.prefix_embedding, 
            mapped_embed,  # Now contains num_embedding_tokens tokens
            self.suffix_embedding
        ], dim=1)
        
        # Squeeze to remove batch dimension for encoding
        combined_embeds_squeezed = combined_embeds.squeeze(0)
        
        # Encode embeddings for API
        encoded_embeds = self._encode_embeddings(combined_embeds_squeezed)
        
        # Call hosted model with grammar constraints
        try:
            completion = self.client.completions.create(
                model=self.model_name,
                prompt="",  # Empty since we're using embeddings
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body={
                    "prompt_embeds": encoded_embeds,
                    "guided_grammar": grammar
                },
            )
            
            generated_text = completion.choices[0].text.strip()
            
            # Log the LLM response if logging is enabled
            self._log_llm_response(
                embedding_vector=embedding_vector if isinstance(embedding_vector, np.ndarray) else embedding_vector.cpu().numpy() if hasattr(embedding_vector, 'cpu') else np.array(embedding_vector),
                generated_text=generated_text,
                metadata={
                    'max_tokens': max_tokens,
                    'temperature': temperature,
                    'source': 'generate_with_grammar'
                }
            )
            
            return generated_text
            
        except Exception as e:
            logger.warning(f"Error during API call: {e}")
            return None
        
    def generate_with_grammar_batch(self, 
                                embedding_vectors, 
                                grammar: Optional[str] = None, 
                                max_tokens: int = 128, 
                                temperature: float = 0.7,
                                max_concurrent: int = 20) -> List[str]:
        """
        Generate output from multiple embedding vectors with grammar constraints using concurrent requests.
        
        Args:
            embedding_vectors: List or tensor of 256-dimensional input vectors
            grammar: Optional grammar override. If None, uses the grammar from registry.
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            max_concurrent: Maximum number of concurrent API requests
            
        Returns:
            List of generated text strings
        """
        if len(embedding_vectors) == 0:
            return []
        
        # Use instance grammar if not overridden
        if grammar is None:
            grammar = self.grammar
        
        # Convert to list of numpy arrays if needed
        if isinstance(embedding_vectors, torch.Tensor):
            embeddings_list = [embedding_vectors[i].cpu().numpy() for i in range(embedding_vectors.shape[0])]
        else:
            embeddings_list = embedding_vectors
        
        # Use ThreadPoolExecutor for concurrent API calls
        with ThreadPoolExecutor(max_workers=min(max_concurrent, len(embeddings_list))) as executor:
            # Submit all generation tasks
            futures = []
            for embedding in embeddings_list:
                future = executor.submit(
                    self._generate_single_with_error_handling,
                    embedding, grammar, max_tokens, temperature
                )
                futures.append(future)
            
            # Collect results in order
            results = []
            for future in futures:
                try:
                    result = future.result(timeout=30)  # 30 second timeout per request
                    results.append(result)
                except Exception as e:
                    logger.warning(f"Batch generation error: {e}")
                    results.append(self._get_fallback_output())
        
        return results

    def _generate_single_with_error_handling(self, embedding_vector, grammar, max_tokens, temperature) -> str:
        """Helper method to generate single query with error handling."""
        try:
            result = self.generate_with_grammar(
                embedding_vector=embedding_vector,
                grammar=grammar,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return result if result is not None else self._get_fallback_output()
        except Exception as e:
            logger.warning(f"Single generation error: {e}")
            return self._get_fallback_output()
    
    def _get_fallback_output(self) -> str:
        """Return a fallback output based on the grammar type."""
        if self.grammar_config.schema == "IMDB":
            return "(title )"
        elif self.grammar_config.schema == "SQLStorm":
            return "(Posts )"
        else:
            return ""
        
    def string_to_embed(self, 
                       text_input: Union[str, List[str]], 
                       model: str = "text-embedding-3-large") -> Optional[np.ndarray]:
        """
        Convert string(s) to 256-dimensional embeddings.
        
        Args:
            text_input: Single string or list of strings to embed
            model: OpenAI embedding model to use
            
        Returns:
            numpy array of shape (256,) for single string or (n, 256) for list of strings
        """
        # Handle single string vs list of strings
        if isinstance(text_input, str):
            texts = [text_input]
            single_input = True
        else:
            texts = text_input
            single_input = False
        
        # Clean texts (replace newlines)
        cleaned_texts = [text.replace("\n", " ") for text in texts]
        
        try:
            # Get embeddings from OpenAI with 256 dimensions
            response = self.embedding_client.embeddings.create(
                input=cleaned_texts, 
                model=model,
                dimensions=256  # Request 256-dimensional embeddings
            )
            
            # Extract embeddings
            embeddings = [data.embedding for data in response.data]
            embeddings_array = np.array(embeddings, dtype=np.float32)
            
            if single_input:
                return embeddings_array[0]  # Shape: (256,)
            else:
                return embeddings_array     # Shape: (n, 256)
                
        except Exception as e:
            logger.warning(f"Error getting embeddings: {e}")
            return None
