"""
Grammar Registry for Constrained Query Generation

This module provides a centralized registry for all grammar variants used in
grammar-constrained inference. Each grammar is stored as a separate .lark file
and the registry tracks associated model paths and metadata.

Usage:
    from grammars import get_grammar, get_grammar_config, list_grammars
    
    # Get just the grammar string
    grammar = get_grammar("imdb_full_21table")
    
    # Get full config including model paths
    config = get_grammar_config("imdb_8table_filtered")
    
    # List all available grammars
    grammars = list_grammars()
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List

GRAMMARS_DIR = Path(__file__).parent


@dataclass
class GrammarConfig:
    """Configuration for a grammar variant."""
    name: str
    description: str
    schema: str  # "IMDB" or "SQLStorm"
    grammar_file: str  # Filename in grammars directory
    num_tables: int
    model_path: Optional[str] = None
    mapping_layer_path: Optional[str] = None
    api_model_name: Optional[str] = None
    
    def get_grammar(self) -> str:
        """Load and return the grammar string from the .lark file."""
        grammar_path = GRAMMARS_DIR / self.grammar_file
        if not grammar_path.exists():
            raise FileNotFoundError(f"Grammar file not found: {grammar_path}")
        return grammar_path.read_text()


# Registry of all available grammars
# NOTE on `schema=` field: the values here ("IMDB", "SQLStorm", "Stack")
# are *workload-set names*, NOT the same as the `db_schema` literal the
# oracle worker contract accepts. For IMDB-backed grammars use db_schema
# = "JOB" at the worker boundary, not "IMDB". See SCHEMA_NAMING.md.
GRAMMAR_REGISTRY: Dict[str, GrammarConfig] = {
    # ==========================================================================
    # IMDB/JOB Schema Grammars
    # ==========================================================================

    "imdb_21table_optional": GrammarConfig(
        name="imdb_21table_optional",
        description="Full IMDB schema, 21 tables, all selectors optional, multi-predicate per table, no md5sum",
        schema="IMDB",
        grammar_file="imdb_21table_optional.lark",
        num_tables=21,
    ),

    "imdb_full_21table": GrammarConfig(
        name="imdb_full_21table",
        description="Full IMDB schema with 21 tables, _filtered pattern with cross-join markers, single predicate per primary table",
        schema="IMDB",
        grammar_file="imdb_full_21table.lark",
        num_tables=21,
        model_path=None,  # Set when model is trained
        mapping_layer_path=None,
        api_model_name=None,
    ),
    
    "imdb_8table_optional": GrammarConfig(
        name="imdb_8table_optional",
        description="Reduced IMDB schema, 8 core tables, all selectors optional, multi-predicate, has md5sum",
        schema="IMDB",
        grammar_file="imdb_8table_optional.lark",
        num_tables=8,
    ),

    "imdb_8table_filtered": GrammarConfig(
        name="imdb_8table_filtered",
        description="Reduced IMDB schema with 8 core tables, _filtered pattern with cross-join markers, single predicate per primary table",
        schema="IMDB",
        grammar_file="imdb_8table_filtered.lark",
        num_tables=8,
        model_path=None,
        mapping_layer_path=None,
        api_model_name=None,
    ),
    
    # ==========================================================================
    # SQLStorm/StackOverflow Schema Grammars
    # ==========================================================================
    
    "sqlstorm": GrammarConfig(
        name="sqlstorm",
        description="SQLStorm/StackOverflow schema with 12 tables, supports timestamps and enum values, all selectors optional",
        schema="SQLStorm",
        grammar_file="sqlstorm.lark",
        num_tables=12,
        model_path=None,
        mapping_layer_path=None,
        api_model_name=None,
    ),

    # ==========================================================================
    # Stack (StackExchange) Schema Grammars
    # ==========================================================================

    "stack": GrammarConfig(
        name="stack",
        description="StackExchange schema, 10 tables, snake_case, site enum filter, optional multi-predicate",
        schema="Stack",
        grammar_file="stack.lark",
        num_tables=10,
    ),
}


def get_grammar(name: str) -> str:
    """
    Get the grammar string for a named grammar variant.
    
    Args:
        name: Name of the grammar (e.g., "imdb_full_21table", "sqlstorm")
        
    Returns:
        The grammar string content
        
    Raises:
        KeyError: If grammar name is not in registry
        FileNotFoundError: If grammar file doesn't exist
    """
    if name not in GRAMMAR_REGISTRY:
        available = ", ".join(GRAMMAR_REGISTRY.keys())
        raise KeyError(f"Unknown grammar '{name}'. Available: {available}")
    
    return GRAMMAR_REGISTRY[name].get_grammar()


def get_grammar_config(name: str) -> GrammarConfig:
    """
    Get the full configuration for a named grammar variant.
    
    Args:
        name: Name of the grammar
        
    Returns:
        GrammarConfig object with all metadata and paths
        
    Raises:
        KeyError: If grammar name is not in registry
    """
    if name not in GRAMMAR_REGISTRY:
        available = ", ".join(GRAMMAR_REGISTRY.keys())
        raise KeyError(f"Unknown grammar '{name}'. Available: {available}")
    
    return GRAMMAR_REGISTRY[name]


def list_grammars() -> List[str]:
    """Return list of all available grammar names."""
    return list(GRAMMAR_REGISTRY.keys())


def list_grammars_by_schema(schema: str) -> List[str]:
    """
    Return list of grammar names for a specific schema.
    
    Args:
        schema: "IMDB" or "SQLStorm"
        
    Returns:
        List of grammar names matching the schema
    """
    return [name for name, config in GRAMMAR_REGISTRY.items() 
            if config.schema == schema]


def register_grammar(config: GrammarConfig) -> None:
    """
    Register a new grammar configuration.
    
    Args:
        config: GrammarConfig object to register
    """
    GRAMMAR_REGISTRY[config.name] = config


def update_grammar_paths(
    name: str,
    model_path: Optional[str] = None,
    mapping_layer_path: Optional[str] = None,
    api_model_name: Optional[str] = None,
) -> None:
    """
    Update the model paths for a grammar configuration.
    
    Args:
        name: Name of the grammar to update
        model_path: Path to the model directory
        mapping_layer_path: Path to the mapping layer weights
        api_model_name: Model name for the API
    """
    if name not in GRAMMAR_REGISTRY:
        raise KeyError(f"Unknown grammar '{name}'")
    
    config = GRAMMAR_REGISTRY[name]
    if model_path is not None:
        config.model_path = model_path
    if mapping_layer_path is not None:
        config.mapping_layer_path = mapping_layer_path
    if api_model_name is not None:
        config.api_model_name = api_model_name
