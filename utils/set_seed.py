# set_seed.py
import os
import random

import numpy as np
import torch
torch.set_float32_matmul_precision("highest")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def set_seed(seed=None):
    if seed is not None:
        torch.manual_seed(seed)
        random.seed(seed)
        np.random.seed(seed)
        os.environ["PYTHONHASHSEED"] = str(seed)
        if device == "cuda":
            torch.cuda.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            torch.backends.cudnn.benchmark = False
            torch.backends.cudnn.deterministic = True
