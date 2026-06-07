import torch
import lightning as L
from lightning.pytorch.loggers import WandbLogger
from lightning.pytorch.callbacks import ModelCheckpoint, RichProgressBar, LearningRateMonitor

from model import VAEModule, build_vocab_simple
from datamodule import VariableLengthDataModule


def get_max_token_value(file_path: str) -> int:
    """Find the maximum token value in the dataset"""
    max_val = 0
    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                tokens = [int(x) for x in line.split(',')]
                max_val = max(max_val, max(tokens))
    return max_val


def train_variable_length_vae(
    data_file: str,
    val_file: str = None,
    checkpoint_path: str = None,
    max_epochs: int = 1000,
    batch_size: int = 32,
    learning_rate: float = 1e-4,
    latent_dim: int = 64,
    project_name: str = "VariableLengthVAE"
):
    """Train a variable length VAE"""
    
    # Find max token value and build vocabulary
    max_token = get_max_token_value(data_file)
    if val_file:
        max_token = max(max_token, get_max_token_value(val_file))
    print(f"Max token value in dataset: {max_token}")
    
    vocab, rev_vocab = build_vocab_simple(max_token)
    print(f"Vocabulary size: {len(vocab)}")
    print(f"Vocab preview: {dict(list(vocab.items())[:5])}")
    
    # Create data module FIRST
    dm = VariableLengthDataModule(
        train_file=data_file,
        val_file=val_file,
        batch_size=batch_size,
        val_split=0.1,
        num_workers=0,  # Set to 0 to avoid multiprocessing issues with vocab
        vocab=vocab  # Pass in constructor
    )
    
    # ALSO set it explicitly to be sure
    dm.set_vocab(vocab)
    print(f"Final check - DataModule vocab set: {dm.vocab is not None}")
    print(f"Final check - DataModule vocab size: {len(dm.vocab) if dm.vocab else 'None'}")
    
    # Create model
    if checkpoint_path and checkpoint_path.endswith('.ckpt'):
        print(f"Loading model from checkpoint: {checkpoint_path}")
        # Load existing model and adapt it
        try:
            old_model = torch.load(checkpoint_path, map_location='cpu')
            print("Loaded old model successfully")
            
            # Create new model with same architecture but new vocab
            model = VAEModule(
                vocab=vocab,
                rev_vocab=rev_vocab,
                bn_size=4,
                d_enc=256,
                d_dec=256,
                d_neck=latent_dim, # 16 as per original code
                kl_factor=0.02,
                min_posterior_std=1e-4,
                enc_nhead=8,
                enc_dim_ff=768,
                enc_dropout=0.1,
                enc_num_layer=3,
                dec_nhead=8,
                dec_dim_ff=768,
                dec_dropout=0.1,
                dec_num_layer=3,
            )
            
            # Try to load compatible weights
            try:
                # Load state dict but be flexible about mismatches
                model_state = model.state_dict()
                if 'state_dict' in old_model:
                    old_state = old_model['state_dict']
                else:
                    old_state = old_model
                
                # Only load weights that match in size
                compatible_weights = {}
                for key in model_state.keys():
                    if key in old_state and model_state[key].shape == old_state[key].shape:
                        compatible_weights[key] = old_state[key]
                        print(f"Loaded weight: {key}")
                    else:
                        print(f"Skipping weight: {key} (shape mismatch or not found)")
                
                model.load_state_dict(compatible_weights, strict=False)
                print(f"Loaded {len(compatible_weights)} compatible weights")
                
            except Exception as e:
                print(f"Could not load weights from checkpoint: {e}")
                print("Starting with random initialization")
                
        except Exception as e:
            print(f"Could not load checkpoint: {e}")
            print("Starting with random initialization")
            model = VAEModule(
                vocab=vocab,
                rev_vocab=rev_vocab,
                bn_size=4,
                d_enc=256,
                d_dec=256,
                d_neck=latent_dim,
                kl_factor=0.02
            )
    else:
        print("Starting with random initialization")
        model = VAEModule(
            vocab=vocab,
            rev_vocab=rev_vocab,
            bn_size=4,
            d_enc=256,
            d_dec=256,
            d_neck=latent_dim,
            kl_factor=0.02,
            min_posterior_std=1e-4,
            enc_nhead=8,
            enc_dim_ff=768,
            enc_dropout=0.1,
            enc_num_layer=3,
            dec_nhead=8,
            dec_dim_ff=768,
            dec_dropout=0.1,
            dec_num_layer=3,
        )
    
    # Setup logging and callbacks
    logger = WandbLogger(project=project_name, save_dir="wandb_logs", log_model=False)
    
    checkpoint_callback = ModelCheckpoint(
        every_n_epochs=10,
        save_top_k=-1,
        save_last=True,
        dirpath="checkpoints/",
        filename="variable_length_vae-{epoch:02d}-{val/loss:.3f}"
    )
    
    # Setup trainer
    trainer = L.Trainer(
        accelerator='gpu',
        devices=4,
        logger=logger,
        callbacks=[checkpoint_callback, RichProgressBar(), LearningRateMonitor()],
        gradient_clip_val=1.0,
        max_epochs=max_epochs,
        precision='16-mixed',
        benchmark=True,
        check_val_every_n_epoch=5,
    )
    
    # Train the model
    trainer.fit(model, datamodule=dm)
    
    return model, trainer


if __name__ == "__main__":
    # Configuration
    DATA_FILE = "train_stack.txt"
    CHECKPOINT_PATH = None  # Fresh train for Stack schema (vocab differs from all existing checkpoints)
    MAX_EPOCHS = 1000
    BATCH_SIZE = 128
    LATENT_DIM = 16  # -> 64-dim latent (bn_size=4 * d_neck=16)
    PROJECT_NAME = "Stack_Plan_VAE"
    
    # Train the model
    model, trainer = train_variable_length_vae(
        data_file=DATA_FILE,
        checkpoint_path=CHECKPOINT_PATH,
        max_epochs=MAX_EPOCHS,
        batch_size=BATCH_SIZE,
        latent_dim=LATENT_DIM,
        project_name=PROJECT_NAME
    )
    
    print("Training completed!")
    
    # Test sampling
    print("\nTesting sampling:")
    with torch.no_grad():
        samples = model.sample(torch.randn(5, LATENT_DIM).to(model.device))
        for i, sample in enumerate(samples):
            print(f"Sample {i+1}: {sample}")