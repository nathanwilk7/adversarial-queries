"""
Dataset classes for embedding-prompted fine-tuning.

This module provides the EmbeddingPromptDataset class and a custom collate function
for batching samples with embeddings and text tokens.
"""

import ast
import torch
import pandas as pd
from tqdm import tqdm
from torch.utils.data import Dataset
from typing import Any, Dict, List


class EmbeddingPromptDataset(Dataset):
    """
    Dataset for embedding + prompt fine-tuning that loads embeddings, query strings,
    and expected outputs from a DataFrame using a chat template format.
    
    Args:
        tokenizer: The tokenizer to use for encoding text
        source: Path to the data file (.csv or .parquet)
        max_seq_len: Maximum sequence length for tokens
        input_embedding_dim: Dimension of input embeddings
        num_embedding_tokens: Number of tokens to use for embedding (default: 4)
        data_multiply: Multiply dataset to simulate multiple epochs (default: 1)
        test_holdout: Number of samples to hold out for testing (default: 0)
    """
    
    def __init__(
        self, 
        tokenizer, 
        source: str, 
        max_seq_len: int = 1024, 
        input_embedding_dim: int = 256, 
        num_embedding_tokens: int = 4,
        data_multiply: int = 1,
        test_holdout: int = 0
    ):
        self.tokenizer = tokenizer
        self.max_seq_len = max_seq_len
        self.input_embedding_dim = input_embedding_dim
        self.num_embedding_tokens = num_embedding_tokens
        self.ignore_index = -100
        
        # Load data
        self.data = self._load_data(source, data_multiply, test_holdout)
        
        # Create system message once for all examples
        self.system_message = "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\nYou are a helpful assistant outputting SQL join specifications for a given join embedding.<|eot_id|>"
        self.system_tokens = self.tokenizer.encode(self.system_message, add_bos=False, add_eos=False)

        # Define prefix and suffix for embedding section
        self.embed_prefix = "<|start_header_id|>embedding<|end_header_id|>\n\n"
        self.embed_suffix = "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
        
        # Pre-tokenize these parts once
        self.prefix_tokens = self.tokenizer.encode(self.embed_prefix, add_bos=False, add_eos=False)
        self.suffix_tokens = self.tokenizer.encode(self.embed_suffix, add_bos=False, add_eos=False)
        
        # Process all samples
        self.processed_data = self._process_samples()
        
        print(f"Dataset initialized with {len(self.processed_data)} samples.")
    
    def _load_data(self, source: str, data_multiply: int, test_holdout: int) -> pd.DataFrame:
        """Load data from file and apply preprocessing."""
        try:
            if source.lower().endswith(".csv"):
                data = pd.read_csv(source)
            elif source.lower().endswith(".parquet"):
                data = pd.read_parquet(source)
            else:
                raise ValueError(f"Unsupported file format: {source}. Use .csv or .parquet.")
            
            # Remove test holdout samples
            if test_holdout > 0:
                data = data.iloc[:-test_holdout]
                print(f"Holding out last {test_holdout} samples for testing")
            
            # Multiply data if requested
            if data_multiply > 1:
                data = pd.concat([data] * data_multiply, ignore_index=True)
                print(f"Data multiplied by {data_multiply}x = {len(data)} total samples")
            
            # Handle string embeddings if needed
            if 'embedding' in data.columns and isinstance(data['embedding'].iloc[0], str):
                print("Parsing string embeddings...")
                data['embedding'] = data['embedding'].apply(self._parse_embedding_safe)
                original_len = len(data)
                data = data.dropna(subset=['embedding'])
                if len(data) < original_len:
                    print(f"Dropped {original_len - len(data)} rows due to parsing errors.")
                    
            return data
            
        except FileNotFoundError:
            raise FileNotFoundError(f"Data source file not found: {source}")
        except Exception as e:
            raise ValueError(f"Failed to load/parse data from {source}: {e}")
    
    def _parse_embedding_safe(self, embedding_str):
        """Parse string representation of embeddings into a list of floats."""
        if not isinstance(embedding_str, str):
            return embedding_str
        try:
            embedding_list = ast.literal_eval(embedding_str)
            if isinstance(embedding_list, list) and all(isinstance(x, (int, float)) for x in embedding_list):
                return [float(x) for x in embedding_list]
            return None
        except:
            return None
    
    def _process_samples(self) -> List[Dict]:
        """Process all samples and tokenize them."""
        processed_data = []
        
        print(f"Tokenizing {len(self.data)} samples...")
        for idx, row in tqdm(self.data.iterrows(), total=len(self.data), desc="Processing samples"):
            try:
                result = self._process_single_sample(idx, row)
                if result is not None:
                    processed_data.append(result)
            except Exception as e:
                print(f"Error processing row {idx}: {e}. Skipping.")
                
        print(f"Finished processing. {len(processed_data)} samples loaded.")
        return processed_data
    
    def _process_single_sample(self, idx: int, row: pd.Series) -> Dict:
        """Process a single sample."""
        # Process embedding
        embedding_data = row['embedding']
        if isinstance(embedding_data, list):
            embedding_tensor = torch.tensor(embedding_data, dtype=torch.float32)
        elif hasattr(embedding_data, 'tolist'):
            embedding_tensor = torch.tensor(embedding_data.tolist(), dtype=torch.float32)
        else:
            print(f"Warning: Row {idx} unexpected embedding type {type(embedding_data)}. Skip.")
            return None
        
        # Verify embedding dimension
        if embedding_tensor.shape[0] != self.input_embedding_dim:
            print(f"Warning: Row {idx} dimension mismatch. "
                  f"Expected {self.input_embedding_dim}, got {embedding_tensor.shape[0]}. Skip.")
            return None
        
        # Get the target output (sql_spec or query_string based on dataset)
        if 'sql_spec' in row:
            target_text = str(row['sql_spec'])
        elif 'query_string' in row:
            target_text = str(row['query_string'])
        else:
            raise ValueError(f"Row {idx} missing 'sql_spec' or 'query_string' column")
        
        # Format assistant response
        assistant_message = f"{target_text}<|eot_id|>"
        assistant_tokens = self.tokenizer.encode(assistant_message, add_bos=False, add_eos=False)
        
        # Mark the position right after the prefix tokens where the embedding will go
        embed_pos = len(self.system_tokens) + len(self.prefix_tokens)
        
        # Construct the prompt tokens (without the embedding placeholder)
        prompt_tokens = self.system_tokens + self.prefix_tokens + self.suffix_tokens
        
        # Calculate total length and truncate if needed
        max_tokens_for_text = self.max_seq_len - self.num_embedding_tokens
        total_len = len(prompt_tokens) + len(assistant_tokens)
        
        if total_len > max_tokens_for_text:
            max_prompt_len = max(1, max_tokens_for_text - len(assistant_tokens))
            min_keep = len(self.system_tokens) + len(self.prefix_tokens) + len(self.suffix_tokens)
            if max_prompt_len < min_keep:
                print(f"Warning: Row {idx} too long, skipping")
                return None
            prompt_tokens = self.system_tokens + self.prefix_tokens + self.suffix_tokens[:max_prompt_len - min_keep]
        
        # Final combined tokens for training
        combined_tokens = prompt_tokens + assistant_tokens
        if len(combined_tokens) > max_tokens_for_text:
            combined_tokens = combined_tokens[:max_tokens_for_text]
            if combined_tokens and self.tokenizer.eos_id not in combined_tokens[-10:]:
                combined_tokens[-1] = self.tokenizer.eos_id
        
        # Extract assistant tokens for labels
        prompt_len = len(prompt_tokens)
        actual_assistant_tokens = combined_tokens[prompt_len:]
        
        return {
            "input_embedding": embedding_tensor,
            "prompt_tokens": prompt_tokens,
            "assistant_tokens": actual_assistant_tokens,
            "insert_pos": embed_pos
        }
    
    def __len__(self) -> int:
        return len(self.processed_data)
    
    def __getitem__(self, idx: int) -> Dict[str, Any]:
        item = self.processed_data[idx]
        return {
            "input_embedding": item["input_embedding"],
            "prompt_tokens": item["prompt_tokens"],
            "assistant_tokens": item["assistant_tokens"],
            "insert_pos": item["insert_pos"]
        }


def embedding_aware_collate_for_transformer_decoder(
    batch: List[Dict[str, Any]], 
    tokenizer, 
    max_seq_len: int, 
    num_embedding_tokens: int = 4
) -> Dict[str, Any]:
    """
    Custom collate function for batches containing embeddings and text tokens.
    
    Args:
        batch: A list of samples from the dataset
        tokenizer: The tokenizer used
        max_seq_len: Maximum sequence length
        num_embedding_tokens: Number of tokens used for embedding (default: 4)
        
    Returns:
        A dictionary with batched embeddings, input_ids, labels, and mask
    """
    ignore_index = -100
    pad_id = tokenizer.pad_id if tokenizer.pad_id is not None else tokenizer.eos_id
    
    # Extract embeddings and insertion positions
    embeddings = [item['input_embedding'] for item in batch]
    insert_positions = [item.get('insert_pos', 1) for item in batch]
    
    # Prepare lists for batched tensors
    input_ids_list, labels_list = [], []
    
    # Find max length in this batch
    max_len_in_batch = 0
    for item in batch:
        max_len_in_batch = max(max_len_in_batch, len(item['prompt_tokens']) + len(item['assistant_tokens']))
    
    # Ensure we don't exceed the global max length
    max_len_in_batch = min(max_len_in_batch, max_seq_len - num_embedding_tokens)
    
    # Process each sample in the batch
    for item in batch:
        prompt_tok, asst_tok = item['prompt_tokens'], item['assistant_tokens']
        
        # Combine tokens and trim if needed
        full_tokens = prompt_tok + asst_tok
        if len(full_tokens) > max_len_in_batch:
            full_tokens = full_tokens[:max_len_in_batch]
            prompt_len = min(len(prompt_tok), max_len_in_batch)
            asst_tok = full_tokens[prompt_len:]
            
            if asst_tok and full_tokens[-1] != tokenizer.eos_id:
                full_tokens[-1] = tokenizer.eos_id
                asst_tok = full_tokens[len(prompt_tok):]
        
        # Add padding
        seq_len = len(full_tokens)
        padding_needed = max_len_in_batch - seq_len
        padded_ids = full_tokens + ([pad_id] * padding_needed)
        input_ids_list.append(torch.tensor(padded_ids, dtype=torch.long))
        
        # Create labels with ignore_index for prompt portion
        prompt_len = len(prompt_tok)
        padded_labels = ([ignore_index] * prompt_len) + asst_tok + ([ignore_index] * padding_needed)
        labels_list.append(torch.tensor(padded_labels, dtype=torch.long))
    
    # Create attention mask
    attention_mask = torch.zeros(len(batch), max_len_in_batch, dtype=torch.bool)
    for i, item in enumerate(batch):
        actual_token_len = min(len(item['prompt_tokens']) + len(item['assistant_tokens']), max_len_in_batch)
        attention_mask[i, :actual_token_len] = True
    
    return {
        'input_embedding': torch.stack(embeddings, 0),
        'input_ids': torch.stack(input_ids_list, 0),
        'labels': torch.stack(labels_list, 0),
        'mask': attention_mask,
        'insert_pos': torch.tensor(insert_positions, dtype=torch.long)
    }