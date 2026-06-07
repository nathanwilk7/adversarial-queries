#!/usr/bin/env python3
"""
Main training script for embedding-prompted fine-tuning.

This script runs the training recipe with the specified config file.

Usage:
    CUDA_VISIBLE_DEVICES="6,7" tune run --nproc_per_node 2 train.py --config configs/sqlstorm.yaml
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.recipe import recipe_main

if __name__ == "__main__":
    recipe_main()
