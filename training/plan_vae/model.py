from math import log
from typing import List, Tuple, Union

import lightning as L
import torch
import torch.nn.functional as F
from torch import nn
from torch.nn.utils.rnn import pad_sequence
from torch.optim.lr_scheduler import LambdaLR
from torch.distributions import Normal, kl_divergence, Categorical
from collections import OrderedDict


START = -1  # Start token value
PAD = -2    # Padding token value

def build_vocab_simple(max_token_value: int = 25):
    """Build vocabulary for simple integer sequences"""
    # Create vocab for integers 0 to max_token_value, plus special tokens
    tokens = list(range(max_token_value + 1)) + [START, PAD]
    vocab = OrderedDict(zip(tokens, range(len(tokens))))
    rev_vocab = OrderedDict(zip(range(len(tokens)), tokens))
    return vocab, rev_vocab

class SafeNormal(Normal):
    @torch.compiler.disable
    def rsample(self, sample_shape: torch.Size = torch.Size()):  # type: ignore # noqa: B008
        return super().rsample(sample_shape)

    @torch.compiler.disable
    def kl_divergence(self, other: Normal):
        return kl_divergence(self, other)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, dropout: float = 0.1, max_len: int = 256):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        position = torch.arange(max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) * (-log(10000.0) / d_model))
        pe = torch.zeros(1, max_len, d_model)
        pe[0, :, 0::2] = torch.sin(position * div_term)
        pe[0, :, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe)

    def forward(self, x):
        x = x + self.pe[:, : x.shape[1], :]
        return self.dropout(x)


class InfoTransformerVAE(L.LightningModule):
    def __init__(
        self,
        vocab: dict,
        rev_vocab: dict,
        bn_size: int = 2,
        d_enc: int = 128,
        d_dec: int = 128,
        d_neck: int = 128,
        kl_factor: float = 0.1,
        min_posterior_std: float = 1e-4,
        enc_nhead: int = 8,
        enc_dim_ff: int = 512,
        enc_dropout: float = 0.1,
        enc_num_layer: int = 6,
        dec_nhead: int = 8,
        dec_dim_ff: int = 256,
        dec_dropout: float = 0.1,
        dec_num_layer: int = 6,
    ):
        super().__init__()
        self.save_hyperparameters()

        self.vocab = vocab
        self.rev_vocab = rev_vocab
        self.vocab_size = len(vocab)

        self.bn_size = bn_size
        self.d_model = d_dec
        self.d_neck = d_neck

        self.kl_factor = kl_factor
        self.min_posterior_std = min_posterior_std

        self.enc_tok_emb = nn.Embedding(self.vocab_size, embedding_dim=d_enc)
        self.enc_pos_enc = PositionalEncoding(d_enc, dropout=enc_dropout)

        self.dec_pos_enc = PositionalEncoding(self.d_model, dropout=enc_dropout)
        self.dec_tok_emb = nn.Embedding(self.vocab_size, embedding_dim=d_dec)
        self.dec_tok_unembed = nn.Linear(d_dec, self.vocab_size)

        self.encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=d_enc,
                nhead=enc_nhead,
                dim_feedforward=enc_dim_ff,
                dropout=enc_dropout,
                activation="gelu",
                batch_first=True,
            ),
            num_layers=enc_num_layer,
        )

        self.decoder = nn.TransformerDecoder(
            nn.TransformerDecoderLayer(
                d_model=d_dec,
                nhead=dec_nhead,
                dim_feedforward=dec_dim_ff,
                dropout=dec_dropout,
                activation="gelu",
                batch_first=True,
            ),
            num_layers=dec_num_layer,
        )

        d_latent = self.bn_size * d_neck
        self.enc_neck = nn.Linear(d_enc * self.bn_size, d_latent * 2)
        self.dec_neck = nn.Linear(d_latent, d_dec * self.bn_size)

        reset(self)

    def encode(self, tokens):
        embed = self.enc_tok_emb(tokens)
        embed = self.enc_pos_enc(embed)

        pad_mask = tokens == self.vocab[PAD]
        embed = self.encoder(embed, src_key_padding_mask=pad_mask)[:, : self.bn_size]
        embed = self.enc_neck(embed.flatten(1))

        mu, sigma = embed.chunk(2, dim=-1)
        sigma = F.softplus(sigma) + self.min_posterior_std

        return mu, sigma

    def decode(self, z, tokens):
        z = self.dec_neck(z).reshape(z.shape[0], self.bn_size, self.d_model)
        embed = self.dec_tok_emb(tokens)
        embed = self.dec_pos_enc(embed)

        decoding = self.decoder(
            tgt=embed,
            memory=z,
            tgt_mask=causal_mask(embed.shape[1], embed.dtype, embed.device),
            tgt_is_causal=True,
        )
        logits = self.dec_tok_unembed(decoding)

        return logits

    def forward(self, tokens):
        mu, sigma = self.encode(tokens)
        post = SafeNormal(mu, sigma)
        z = mu + sigma * torch.randn_like(mu)

        logits = self.decode(z, tokens)

        loss_tokens = tokens[:, 1:]
        loss_logits = logits[:, :-1]

        recon_loss = F.cross_entropy(loss_logits.permute(0, 2, 1), loss_tokens)
        kldiv = post.kl_divergence(Normal(0, 1)).mean()

        loss = recon_loss + self.hparams.kl_factor * kldiv
        loss = loss.mean()

        with torch.no_grad():
            preds = loss_logits.argmax(dim=-1)
            hits = loss_tokens == preds

            token_acc = hits.float().mean()
            string_acc = hits.all(dim=1).float().mean()
            sigma_mean = sigma.mean()

        return dict(
            loss=loss,
            z=z,
            recon_loss=recon_loss,
            kldiv=kldiv,
            recon_token_acc=token_acc,
            recon_string_acc=string_acc,
            sigma_mean=sigma_mean,
            mu=mu,
            sigma=sigma,
        )


class VAEModule(L.LightningModule):
    def __init__(
        self,
        vocab: dict,
        rev_vocab: dict,
        bn_size: int = 2,
        d_enc: int = 128,
        d_dec: int = 128,
        d_neck: int = 128,
        kl_factor: float = 0.1,
        min_posterior_std: float = 1e-4,
        enc_nhead: int = 8,
        enc_dim_ff: int = 512,
        enc_dropout: float = 0.1,
        enc_num_layer: int = 6,
        dec_nhead: int = 8,
        dec_dim_ff: int = 256,
        dec_dropout: float = 0.1,
        dec_num_layer: int = 6,
    ):
        super().__init__()
        self.save_hyperparameters()
        self.model = InfoTransformerVAE(**self.hparams)

        self.max_string_length = 90

        self.vocab = vocab
        self.rev_vocab = rev_vocab

    def forward(self, tokens):
        """
        Forward pass expecting pre-encoded tensors from dataloader
        """

        # Handle both cases for now
        if isinstance(tokens, torch.Tensor):
            # Already encoded by dataloader
            pass
        elif isinstance(tokens, list):
            # Fallback: encode here if dataloader didn't do it
            print("WARNING: Encoding in forward pass - dataloader should handle this")
            tokens = encode_batch_simple(tokens, self.vocab).to(self.device)
        else:
            raise ValueError(f"Expected tokens to be tensor or list, got {type(tokens)}")
        
        stats = self.model(tokens)
        return stats

    def training_step(self, batch, batch_idx):
        out = self(batch)

        # import ipdb; ipdb.set_trace()  # Debugging breakpoint

        out = {f"train/{k}": v for k, v in out.items() if k not in ("z", "mu", "sigma")}
        self.log_dict(out, prog_bar=True, logger=True)

        return out["train/loss"]

    def validation_step(self, batch, batch_idx):
        out = self(batch)

        # import ipdb; ipdb.set_trace()  # Debugging breakpoint

        out = {f"val/{k}": v for k, v in out.items() if k not in ("z", "mu", "sigma")}
        self.log_dict(out, prog_bar=True, logger=True)

        return out["val/loss"]

    def configure_optimizers(self):
        opt = torch.optim.AdamW(
            self.parameters(), lr=1e-4, weight_decay=0.01, betas=(0.9, 0.99)
        )
        lr_sched = LambdaLR(opt, lambda step: min(1.0, step / 2048))

        return {
            "optimizer": opt,
            "lr_scheduler": {"scheduler": lr_sched, "interval": "step", "frequency": 1},
        }

    @torch.no_grad()
    def sample(self, z: torch.Tensor):
        pr = torch.get_float32_matmul_precision()
        torch.set_float32_matmul_precision("medium")
        tr = self.training
        self.eval()

        if z.ndim == 1:
            z = z.unsqueeze(0)

        n = z.shape[0]
        z = z.reshape(n, self.hparams.bn_size * self.hparams.d_neck).to(dtype=torch.float32)

        tokens = torch.full((n, 1), fill_value=self.vocab[START], device=self.device)
        while True:
            logits = self.model.decode(z, tokens)[:, -1:]
            sample = Categorical(logits=logits).sample()

            tokens = torch.hstack([tokens, sample])

            stop_mask = (tokens == self.vocab[PAD]).any(dim=-1).all()
            if stop_mask or tokens.shape[-1] > self.max_string_length:
                break

        tokens = decode_batch_simple(tokens, self.rev_vocab)

        self.train(tr)
        torch.set_float32_matmul_precision(pr)
        return tokens


def causal_mask(sz: int, dtype: torch.dtype, device: torch.device):
    return torch.triu(
        torch.full((sz, sz), float("-inf"), dtype=dtype, device=device),
        diagonal=1,
    )


def reset(module: InfoTransformerVAE):
    for mod in module.modules():
        if isinstance(mod, nn.Embedding):
            nn.init.normal_(mod.weight, std=module.d_model**-0.5)
        elif isinstance(mod, nn.Linear):
            nn.init.xavier_uniform_(mod.weight)
            if mod.bias is not None:
                nn.init.zeros_(mod.bias)

    for mod in module.modules():
        if isinstance(mod, nn.MultiheadAttention):
            mod._reset_parameters()


def encode_batch_simple(batch: Union[List[List[int]], List[int]], vocab) -> torch.Tensor:
    """
    Simple encoding for variable length integer sequences
    """
    if isinstance(batch[0], int):
        batch = [batch]

    # Add START and PAD tokens
    encodings = [[vocab[START]] + [vocab[token] for token in seq] + [vocab[PAD]] 
                 for seq in batch]

    encodings = pad_sequence(
        [torch.tensor(enc) for enc in encodings],
        batch_first=True,
        padding_value=vocab[PAD],
    )
    return encodings


def decode_batch_simple(batch: torch.Tensor, rev_vocab) -> List[List[int]]:
    """
    Simple decoding for variable length integer sequences
    """
    if batch.ndim == 1:
        batch = batch.unsqueeze(0)

    def decode_single(tokens: torch.Tensor) -> List[int]:
        decode = tokens.tolist()
        decode = [rev_vocab[item] for item in decode]
        
        # Remove START token if present
        if START in decode:
            decode = decode[decode.index(START) + 1:]
        
        # Remove PAD token and everything after it
        if PAD in decode:
            decode = decode[:decode.index(PAD)]

        return decode

    # Cut out start token
    batch = batch[:, 1:]
    decodings = [decode_single(tokens) for tokens in batch]

    return decodings