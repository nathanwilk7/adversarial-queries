"""Fine-tune the ADVQ-IMDB plan VAE on Postgres-planner plans (Path A).

Warm-starts from `checkpoints/best_64.ckpt` (the Grammars 1-4 DuckDB-planner
plan VAE) and continues training on train_pg.txt / val_pg.txt — the 90/10
split of pg_plans.jsonl shipped in bayes-lqo-20260516-pgsql/.

Vocab is identical (23 tokens, bare ints 0..20 + START + PAD), architecture
is the same, so every weight transfers. Expect rapid convergence from the
already-decent starting point (93% token, 27% exact on PG plans).

Standalone — does not modify the existing train_vae.py (which is wired for
Stack training). Activate your own env (torch + lightning + wandb), then:

    cd adversarial-queries/plan_vae
    python train_vae_pg.py
"""

import lightning as L
import torch
from lightning.pytorch.callbacks import LearningRateMonitor, ModelCheckpoint, RichProgressBar
from lightning.pytorch.loggers import WandbLogger

from datamodule import VariableLengthDataModule
from model import VAEModule, build_vocab_simple


# ---------- config (edit if you need to override) ----------
DATA_FILE = "train_pg.txt"
VAL_FILE = "val_pg.txt"
CHECKPOINT_PATH = "checkpoints/best_64.ckpt"   # warm-start from ADVQ-IMDB DuckDB VAE
OUT_DIR = "checkpoints_pg"                      # don't collide with the Stack run's checkpoints/
PROJECT_NAME = "PG_Plan_VAE"
MAX_EPOCHS = 100        # fine-tune budget; cut early if val/loss plateaus
BATCH_SIZE = 128
LATENT_DIM = 16
DEVICES = 4             # set to "auto" or an int matching your GPU count
# -----------------------------------------------------------


def get_max_token_value(path: str) -> int:
    m = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                m = max(m, max(int(x) for x in line.split(",")))
    return m


def warm_start_from(checkpoint_path: str, vocab, rev_vocab):
    """Build VAEModule and copy every matching-shape weight from `checkpoint_path`."""
    model = VAEModule(
        vocab=vocab, rev_vocab=rev_vocab,
        bn_size=4, d_enc=256, d_dec=256, d_neck=LATENT_DIM,
        kl_factor=0.02, min_posterior_std=1e-4,
        enc_nhead=8, enc_dim_ff=768, enc_dropout=0.1, enc_num_layer=3,
        dec_nhead=8, dec_dim_ff=768, dec_dropout=0.1, dec_num_layer=3,
    )
    state = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    old_sd = state.get("state_dict", state)
    new_sd = model.state_dict()
    transferred = {k: v for k, v in old_sd.items()
                   if k in new_sd and new_sd[k].shape == v.shape}
    missing_or_mismatch = [k for k in new_sd if k not in transferred]
    if missing_or_mismatch:
        print(f"WARNING: {len(missing_or_mismatch)} keys NOT loaded (shape mismatch / not in ckpt):")
        for k in missing_or_mismatch[:5]:
            print(f"  - {k}: target {tuple(new_sd[k].shape)}, ckpt {tuple(old_sd.get(k, torch.zeros(0)).shape) if k in old_sd else 'absent'}")
    model.load_state_dict(transferred, strict=False)
    print(f"warm-started: {len(transferred)} / {len(new_sd)} params restored from {checkpoint_path}")
    return model


def main():
    max_token = max(get_max_token_value(DATA_FILE), get_max_token_value(VAL_FILE))
    vocab, rev_vocab = build_vocab_simple(max_token)
    print(f"max token value: {max_token}    vocab size: {len(vocab)}")
    print(f"vocab preview:   {dict(list(vocab.items())[:5])}")

    dm = VariableLengthDataModule(
        train_file=DATA_FILE, val_file=VAL_FILE, batch_size=BATCH_SIZE,
        val_split=0.0,    # we provided a real val file
        num_workers=0,
        vocab=vocab,
    )
    dm.set_vocab(vocab)

    model = warm_start_from(CHECKPOINT_PATH, vocab, rev_vocab)

    logger = WandbLogger(project=PROJECT_NAME, save_dir="wandb_logs", log_model=False)
    ckpt_cb = ModelCheckpoint(
        every_n_epochs=5,
        save_top_k=-1,
        save_last=True,
        dirpath=OUT_DIR,
        filename="pg_plan_vae-{epoch:02d}-{val/loss:.3f}",
    )
    trainer = L.Trainer(
        accelerator="gpu",
        devices=DEVICES,
        logger=logger,
        callbacks=[ckpt_cb, RichProgressBar(), LearningRateMonitor()],
        gradient_clip_val=1.0,
        max_epochs=MAX_EPOCHS,
        precision="16-mixed",
        benchmark=True,
        check_val_every_n_epoch=1,
    )
    trainer.fit(model, datamodule=dm)
    print("training complete.")


if __name__ == "__main__":
    main()
