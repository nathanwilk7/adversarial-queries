import lightning as L
import torch
from torch.utils.data import Dataset, DataLoader
from torch.nn.utils.rnn import pad_sequence
from typing import List
import random


class VariableLengthSequenceDataset(Dataset):
    def __init__(self, file_path: str):
        self.sequences = []
        self.load_data(file_path)
    
    def load_data(self, file_path: str):
        """Load sequences from text file"""
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    # Parse comma-separated integers
                    sequence = [int(x) for x in line.split(',')]
                    self.sequences.append(sequence)
        
        print(f"Loaded {len(self.sequences)} sequences")
        print(f"Sequence lengths: min={min(len(s) for s in self.sequences)}, "
              f"max={max(len(s) for s in self.sequences)}, "
              f"avg={sum(len(s) for s in self.sequences) / len(self.sequences):.1f}")
    
    def __len__(self):
        return len(self.sequences)
    
    def __getitem__(self, idx):
        return self.sequences[idx]


class VariableLengthDataModule(L.LightningDataModule):
    def __init__(
        self, 
        train_file: str,
        val_file: str = None,
        batch_size: int = 32,
        val_split: float = 0.1,
        num_workers: int = 4,
        vocab: dict = None
    ):
        super().__init__()
        self.train_file = train_file
        self.val_file = val_file
        self.batch_size = batch_size
        self.val_split = val_split
        self.num_workers = num_workers
        self.vocab = vocab
        print(f"DataModule init: vocab is {'set' if vocab is not None else 'None'}")
        
    def set_vocab(self, vocab):
        """Explicitly set vocabulary after creation"""
        self.vocab = vocab
        print(f"DataModule vocab explicitly set: {self.vocab is not None}")
        
    def setup(self, stage: str = None):
        print(f"DataModule setup called: vocab is {'set' if self.vocab is not None else 'None'}")
        if stage == "fit" or stage is None:
            # Load training data
            full_dataset = VariableLengthSequenceDataset(self.train_file)
            
            if self.val_file is not None:
                # Use separate validation file
                self.train_dataset = full_dataset
                self.val_dataset = VariableLengthSequenceDataset(self.val_file)
            else:
                # Split training data
                total_size = len(full_dataset)
                val_size = int(total_size * self.val_split)
                train_size = total_size - val_size
                
                self.train_dataset, self.val_dataset = torch.utils.data.random_split(
                    full_dataset, [train_size, val_size],
                    generator=torch.Generator().manual_seed(42)
                )
    
    def train_dataloader(self):
        return DataLoader(
            self.train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
            collate_fn=self._collate_fn
        )
    
    def val_dataloader(self):
        return DataLoader(
            self.val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            collate_fn=self._collate_fn
        )
    
    def _collate_fn(self, batch):
        """Custom collate function to handle variable length sequences"""
        # print(f"Collate function called: vocab is {'set' if self.vocab is not None else 'None'}")
        # print(f"Collate function self.vocab type: {type(self.vocab)}")
        if hasattr(self, 'vocab') and self.vocab is not None:
            # print(f"Vocab keys sample: {list(self.vocab.keys())[:5]}")
            return self._encode_batch_to_tensor(batch)
        else:
            print("WARNING: vocab is None in datamodule, returning raw batch")
            print(f"self has vocab attr: {hasattr(self, 'vocab')}")
            print(f"self.__dict__ keys: {list(self.__dict__.keys())}")
            return batch
    
    def _encode_batch_to_tensor(self, batch):
        """Convert batch of sequences to padded tensor"""
        START = -1
        PAD = -2
        
        # print(f"Encoding batch of size {len(batch)} with vocab size {len(self.vocab)}")
        # print(f"Sample batch item: {batch[0][:5] if len(batch[0]) > 5 else batch[0]}")
        
        try:
            # Add START and PAD tokens
            encodings = [[self.vocab[START]] + [self.vocab[token] for token in seq] + [self.vocab[PAD]] 
                         for seq in batch]

            encodings = pad_sequence(
                [torch.tensor(enc) for enc in encodings],
                batch_first=True,
                padding_value=self.vocab[PAD],
            )
            # print(f"Encoded tensor shape: {encodings.shape}")
            return encodings
        except Exception as e:
            print(f"Error in encoding: {e}")
            print(f"Problematic token found in sequence: {batch[0]}")
            raise