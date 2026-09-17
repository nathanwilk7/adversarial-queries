"""
Combined query+plan VAE objective for adversarial query generation.
Query VAE uses a frozen LLM with 256-dim embeddings; plan VAE uses plan_vae with simple integer encoding.
"""

import logging
import numpy as np
import torch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from optimization.lolbo.latent_space_objective import LatentSpaceObjective
from training.plan_vae.model import VAEModule, encode_batch_simple
from optimization.objectives.your_objective_functions import OBJECTIVE_FUNCTIONS_DICT
from optimization.query_inference.grammar_constrained_inference import GrammarConstrainedInference
from grammars import get_grammar
from grammars import get_grammar_config

logger = logging.getLogger(__name__)


class AdversarialQueryVAEObjective(LatentSpaceObjective):
    '''Objective class for adversarial query generation using combined query VAE + plan VAE

    Enhanced with query embedding caching for efficient recentering operations.
    Configured for SQLStorm schema by default.
    '''

    def __init__(
        self,
        path_to_plan_vae_statedict="../../training/plan_vae/checkpoints/best_64.ckpt",
        path_to_query_vae_model="../query_inference/epoch_0",
        path_to_mapping_layer="../query_inference/mapping_layer_epoch_0.pt",
        grammar_name="imdb_full_21table",  # Use IMDB grammar by default
        query_dim=256,  # query VAE latent dimension
        plan_dim=64,    # plan VAE latent dimension
        task_id=None,
        task_specific_args=[],
        xs_to_scores_dict={},
        xs_to_censoring_dict={},
        num_calls=0,
        api_base_url="http://localhost:8000/v1",
        api_model_name=None,
        # `schema` is forwarded verbatim to OBJECTIVE_FUNCTIONS_DICT[task_id]
        # and ultimately becomes AdversarialQueryInput.db_schema. The worker's
        # pydantic contract requires "JOB"/"SQLStorm"/"JOB-Complex"/"Stack".
        # Use "JOB" for IMDB grammars (not "IMDB"). See SCHEMA_NAMING.md.
        schema: str = "JOB",
        db_backend: str = "duckdb",
        timeout_ms: int = 30000,
        **kwargs
    ):
        self.query_dim = query_dim
        self.plan_dim = plan_dim
        self.dim = query_dim + plan_dim
        self.path_to_plan_vae_statedict = path_to_plan_vae_statedict
        self.path_to_query_vae_model = path_to_query_vae_model
        self.path_to_mapping_layer = path_to_mapping_layer
        self.grammar_name = grammar_name
        self.api_base_url = api_base_url
        self.api_model_name = api_model_name
        self.schema = schema
        self.db_backend = db_backend
        self.timeout_ms = timeout_ms

        # Load grammar from registry
        self.grammar_string = get_grammar(grammar_name)

        # Set fallback query based on schema
        config = get_grammar_config(grammar_name)
        if config.schema == "SQLStorm":
            self.fallback_query = "(Posts )"
        elif config.schema == "Stack":
            self.fallback_query = "(question )"
        else:
            self.fallback_query = "(title )"

        # Initialize query embedding cache for recentering optimization
        self.query_embedding_cache = {}
        self.cache_hits = 0
        self.cache_misses = 0

        # Initialize the adversarial query objective
        self.objective_function = OBJECTIVE_FUNCTIONS_DICT[task_id](
            *task_specific_args,
            schema=self.schema,
            db_backend=self.db_backend,
            timeout_ms=self.timeout_ms,
        )

        # Initialize constraint functions if any
        self.constraint_functions = []

        super().__init__(
            num_calls=num_calls,
            xs_to_scores_dict=xs_to_scores_dict,
            xs_to_censoring_dict=xs_to_censoring_dict,
            task_id=task_id,
            init_vae=True,
        )

    def initialize_vae(self, enable_llm_logging: bool = True):
        '''Initialize both VAEs - plan VAE (trainable) and query VAE (frozen)

        Args:
            enable_llm_logging: If True, enables logging of all LLM-generated responses
        '''
        # Load plan VAE (will be updated during optimization)
        self.plan_vae = VAEModule.load_from_checkpoint(self.path_to_plan_vae_statedict).cuda()

        # Initialize query VAE interface (frozen LLM) with grammar from registry
        self.query_vae = GrammarConstrainedInference(
            grammar_name=self.grammar_name,
            model_path=self.path_to_query_vae_model,
            mapping_layer_path=self.path_to_mapping_layer,
            api_base_url=self.api_base_url,
            api_model_name=self.api_model_name,
        )

        # Enable LLM response logging by default
        if enable_llm_logging:
            self.query_vae.enable_llm_logging()

        # Set the main vae attribute for compatibility
        self.vae = self.plan_vae

    def clear_query_cache(self):
        '''Clear the query embedding cache and reset statistics'''
        self.query_embedding_cache.clear()
        self.cache_hits = 0
        self.cache_misses = 0
        logger.debug("Query embedding cache cleared")

    def get_cache_stats(self):
        '''Get cache usage statistics'''
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = self.cache_hits / total_requests if total_requests > 0 else 0
        return {
            'cache_size': len(self.query_embedding_cache),
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_rate': hit_rate
        }

    def vae_decode(self, z):
        '''Decode combined latent space to query+plan strings using batch processing'''
        if type(z) is np.ndarray:
            z = torch.from_numpy(z).float()

        z = z.cuda()  # Ensure z is on the correct device

        # Split combined latent space
        z_query = z[:, :self.query_dim]  # First 256 dims for query
        z_plan = z[:, self.query_dim:]   # Last 64 dims for plan

        # Decode queries using batch query VAE
        logger.debug(f"Generating {z_query.shape[0]} queries in batch")
        queries = self.query_vae.generate_with_grammar_batch(
            embedding_vectors=z_query,  # Pass entire tensor
            grammar=self.grammar_string,
            max_tokens=64,
            temperature=0.7,
            max_concurrent=min(20, z_query.shape[0])  # Limit concurrent requests
        )

        # Ensure we have fallback queries for any that failed
        queries = [query if query else self.fallback_query for query in queries]

        # Decode plans using plan VAE (simple encoding)
        self.plan_vae.eval()
        with torch.no_grad():
            plans = self.plan_vae.sample(z=z_plan)

        # Combine queries and plans with [SEP] separator
        combined_strings = []
        for query, plan in zip(queries, plans):
            plan_str = ','.join(map(str, plan))
            combined_str = f"{query}[SEP]{plan_str}"
            combined_strings.append(combined_str)

        return combined_strings

    def query_oracle(self, x, timeouts_list=None):
        '''Query the adversarial oracle'''
        if timeouts_list is None:
            scores_list, censoring_list = self.objective_function.query_black_box(x)
        else:
            scores_list, censoring_list = self.objective_function.query_black_box(x, timeouts_list)
        return scores_list, censoring_list

    def vae_forward(self, xs_batch, use_cache=True):
        '''Encode combined strings to latent space using batch processing

        Args:
            xs_batch: List of combined query[SEP]plan strings
            use_cache: If True, cache and reuse query embeddings to avoid re-computation
        '''
        query_strings = []
        plans_for_vae = []

        # Parse all inputs first
        for x in xs_batch:
            # Parse combined string
            if '[SEP]' in x:
                query_str, plan_str = x.split('[SEP]', 1)
                plan_str = plan_str.strip()
                # Parse plan string to list of integers
                try:
                    if ',' in plan_str:
                        plan = [int(p.strip()) for p in plan_str.split(',')]
                    else:
                        plan = [int(p) for p in plan_str.split()]
                except ValueError:
                    plan = [0]  # Default plan if parsing fails
            else:
                query_str = x
                plan = [0]  # Default plan

            query_strings.append(query_str)
            plans_for_vae.append(plan)

        if use_cache:
            logger.debug("Using cached query embeddings where available")
            query_embeddings = []
            queries_to_encode = []
            query_indices_to_encode = []

            # Check cache for each query
            for i, query_str in enumerate(query_strings):
                if query_str in self.query_embedding_cache:
                    query_embeddings.append(self.query_embedding_cache[query_str])
                    self.cache_hits += 1
                else:
                    query_embeddings.append(None)  # Placeholder
                    queries_to_encode.append(query_str)
                    query_indices_to_encode.append(i)
                    self.cache_misses += 1

            # Batch encode only uncached queries
            if queries_to_encode:
                logger.debug(f"Encoding {len(queries_to_encode)} new queries, reusing {len(query_strings) - len(queries_to_encode)} cached")
                new_embeddings = self.query_vae.string_to_embed(queries_to_encode)
                if new_embeddings is None:
                    new_embeddings = np.zeros((len(queries_to_encode), self.query_dim))

                # Update cache and fill in embeddings
                for i, (idx, embedding) in enumerate(zip(query_indices_to_encode, new_embeddings)):
                    self.query_embedding_cache[queries_to_encode[i]] = embedding
                    query_embeddings[idx] = embedding
            else:
                logger.debug(f"All {len(query_strings)} queries found in cache")

            # Convert to tensor
            query_zs = torch.from_numpy(np.array(query_embeddings)).float().cuda()

            # Print cache statistics periodically
            stats = self.get_cache_stats()
            if (self.cache_hits + self.cache_misses) % 100 == 0:  # Every 100 requests
                logger.debug(f"Cache stats - size: {stats['cache_size']}, hit rate: {stats['hit_rate']:.2%}")

        else:
            # Normal mode: batch encode all queries
            logger.debug(f"Encoding {len(query_strings)} query strings in batch")
            query_embeddings = self.query_vae.string_to_embed(query_strings)  # Pass list of strings

            # Handle case where batch embedding fails
            if query_embeddings is None:
                query_embeddings = np.zeros((len(query_strings), self.query_dim))

            # Convert to tensor
            query_zs = torch.from_numpy(query_embeddings).float().cuda()

        # Encode plans using plan VAE with simple encoding
        plan_tensor = encode_batch_simple(plans_for_vae, self.plan_vae.vocab).cuda()

        # Get plan latent codes and VAE loss
        with torch.no_grad():
            plan_dict = self.plan_vae(plan_tensor)
            plan_zs = plan_dict['mu']  # Use mean of latent distribution
            vae_loss = plan_dict['loss']

        # Combine latent codes
        combined_z = torch.cat([query_zs, plan_zs], dim=1)

        return combined_z, vae_loss

    def _parse_plan_from_x(self, x):
        '''Helper to parse plan from combined string'''
        if '[SEP]' in x:
            _, plan_str = x.split('[SEP]', 1)
            try:
                if ',' in plan_str:
                    return [int(p.strip()) for p in plan_str.split(',')]
                else:
                    return [int(p) for p in plan_str.split()]
            except ValueError:
                return [0]
        return [0]

    def compute_constraints(self, xs_batch):
        '''Compute constraints if any'''
        if len(self.constraint_functions) == 0:
            return None
        # Implement constraint computation if needed
        return None
