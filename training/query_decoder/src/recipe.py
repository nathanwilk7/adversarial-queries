#!/usr/bin/env python3
"""
Training Recipe for Embedding-Prompted Fine-Tuning.

This module contains the main training recipe for fine-tuning language models
with embedding-based soft prompts using distributed training.

Usage:
    CUDA_VISIBLE_DEVICES="6,7" tune run --nproc_per_node 2 train.py --config configs/sqlstorm.yaml
"""

import sys
import time
import os
from functools import partial
from typing import Any, Dict, List, Optional, Union
from warnings import warn

import torch
from torch import nn
from torch.utils.data import DataLoader
from torch.distributed import destroy_process_group, init_device_mesh, init_process_group
from torch.distributed._tensor import DTensor
from torch.distributed.tensor.parallel import parallelize_module
from torch.optim import Optimizer
from torchdata.stateful_dataloader.sampler import StatefulDistributedSampler
from omegaconf import DictConfig
from tqdm import tqdm

from torchtune import config, modules, training, utils
from torchtune.config._utils import _get_component_from_path
from torchtune.recipe_interfaces import FTRecipeInterface
from torchtune.training import DummyProfiler, PROFILER_KEY
from torchtune.training.activations import apply_selective_activation_checkpointing
from torchtune.training.checkpointing._checkpoint_client import CheckpointClient, TrainingProgress
from torchtune.training.lr_schedulers import get_lr

# Import local modules
from src.model import EmbeddingPromptFullModel
from src.dataset import EmbeddingPromptDataset, embedding_aware_collate_for_transformer_decoder

log = utils.get_logger("DEBUG")


class EmbeddingFinetuneRecipe(FTRecipeInterface):
    """
    Recipe for fine-tuning language models with embedding inputs.
    
    This recipe extends the standard fine-tuning approach to support embedding-based prompting,
    where an input embedding is mapped to the model's hidden space and prepended to the input sequence.
    """
    
    def __init__(self, cfg: DictConfig) -> None:
        device_type = cfg.device
        self._device = utils.get_device(device=device_type)
        self._dtype = training.get_dtype(cfg.dtype, device=self._device)
        self._checkpoint_client = CheckpointClient(cfg)
        
        if self._dtype == torch.float16:
            raise ValueError("Full fp16 training is not supported. Please use bf16 or fp32 instead.")
            
        # Set up distributed training
        self._enable_async_checkpointing = cfg.get("enable_async_checkpointing", False)
        self.fsdp_cpu_offload = cfg.get("fsdp_cpu_offload", False)
        self.distributed_backend = training.get_distributed_backend(
            device_type,
            offload_ops_to_cpu=self.fsdp_cpu_offload or self._enable_async_checkpointing,
        )
        init_process_group(self.distributed_backend)
        
        # Initialize distributed variables
        self.world_size, self.rank = utils.get_world_size_and_rank()
        self._is_rank_zero = self.rank == 0
        self.tensor_parallel_plan = config.instantiate(cfg.get("tensor_parallel_plan", None))
        self.tensor_parallel_dim = cfg.get("tensor_parallel_dim", 1)
        
        if self.tensor_parallel_dim > 1 and self.tensor_parallel_plan is None:
            raise ValueError("Tensor Parallel plan needed when tensor parallel is enabled.")
        if self.world_size % self.tensor_parallel_dim != 0:
            raise ValueError(f"world_size {self.world_size} must be divisible by tensor_parallel_dim {self.tensor_parallel_dim}")
        if self.tensor_parallel_dim > 1 and cfg.optimizer.get("fused", False):
            raise ValueError("Tensor parallelism is incompatible with fused optimizer.")
            
        self.data_parallel_dim = self.world_size // self.tensor_parallel_dim
        
        # Logging attributes
        self._output_dir = cfg.output_dir
        self._log_every_n_steps = cfg.get("log_every_n_steps", 1)
        self._log_peak_memory_stats = cfg.get("log_peak_memory_stats", False)
        if self._log_peak_memory_stats and device_type != "cuda":
            log.info("log_peak_memory_stats set to True but not using CUDA. Setting to False.")
            self._log_peak_memory_stats = False
            
        # Training config
        self._resume_from_checkpoint = cfg.resume_from_checkpoint
        self._gradient_accumulation_steps = cfg.gradient_accumulation_steps
        self._optimizer_in_bwd = cfg.get("optimizer_in_bwd", False)
        self._clip_grad_norm = cfg.get("clip_grad_norm", None)
        
        # Optimizer in backward validation
        if self._optimizer_in_bwd:
            if self._clip_grad_norm is not None:
                raise RuntimeError("Gradient clipping not supported with optimizer in bwd.")
            if self._gradient_accumulation_steps > 1:
                raise RuntimeError("Gradient accumulation not supported with optimizer in bwd.")
                
        # Activation checkpointing/offloading
        self._enable_activation_checkpointing = cfg.get("enable_activation_checkpointing", False)
        self._enable_activation_offloading = cfg.get("enable_activation_offloading", False)
        if self._enable_activation_offloading:
            if device_type != "cuda":
                raise RuntimeError("Activation offloading only supported on CUDA")
            if not self._enable_activation_checkpointing:
                raise RuntimeError("Activation offloading requires activation checkpointing")
                
        # Save embedding input dimension from config
        self.input_embedding_dim = cfg.dataset.get("input_embedding_dim", 256)
        self.num_embedding_tokens = cfg.get("num_embedding_tokens", 4)
        
        # Initialize training state
        self.seed = training.set_seed(seed=cfg.seed, debug_mode=cfg.get("cudnn_deterministic_mode", None))
        self.epochs_run = 0
        self.total_epochs = cfg.epochs
        self.max_steps_per_epoch = cfg.max_steps_per_epoch
        self.global_step = 0
        
    def _update_recipe_state(self, ckpt_dict: Dict[str, Any]) -> None:
        """Updates the recipe state from checkpoint."""
        try:
            self.epochs_run = ckpt_dict[training.EPOCHS_KEY]
            
            if self.seed != ckpt_dict[training.SEED_KEY]:
                warn(f"Seed mismatch, using checkpoint value: {ckpt_dict[training.SEED_KEY]}")
                self.seed = ckpt_dict[training.SEED_KEY]
            if self.max_steps_per_epoch != ckpt_dict[training.MAX_STEPS_KEY]:
                warn(f"max_steps_per_epoch mismatch, using checkpoint: {ckpt_dict[training.MAX_STEPS_KEY]}")
                self.max_steps_per_epoch = ckpt_dict[training.MAX_STEPS_KEY]
            if self.total_epochs != ckpt_dict[training.TOTAL_EPOCHS_KEY]:
                warn(f"total_epochs mismatch, using config value: {self.total_epochs}")
                
        except KeyError as e:
            raise KeyError("Checkpoint missing required keys for recipe state update.") from e
            
    def setup(self, cfg: DictConfig) -> None:
        """Setup the recipe including model, tokenizer, optimizer, and data."""
        if self.fsdp_cpu_offload:
            training.set_torch_num_threads()
            
        if self._is_rank_zero:
            self._metric_logger = config.instantiate(cfg.metric_logger)
            self._metric_logger.log_config(cfg)
            
        # Load the base model
        checkpoint_dict = self._checkpoint_client.load_base_checkpoint()
        
        # Initialize tokenizer
        self._tokenizer = config.instantiate(cfg.tokenizer)
        
        self._compile = cfg.get("compile", False)
        self._model = self._setup_model(
            cfg_model=cfg.model,
            input_embedding_dim=self.input_embedding_dim,
            num_embedding_tokens=self.num_embedding_tokens,
            enable_activation_checkpointing=self._enable_activation_checkpointing,
            enable_activation_offloading=self._enable_activation_offloading,
            custom_sharded_layers=cfg.get("custom_sharded_layers", None),
            fsdp_cpu_offload=self.fsdp_cpu_offload,
            reshard_after_forward=cfg.get("fsdp_reshard_after_forward", True),
            model_state_dict=checkpoint_dict[training.MODEL_KEY],
            ac_mode=cfg.get("ac_mode", None),
            ac_option=cfg.get("ac_option", None),
        )
        
        # Initialize optimizer
        self._optimizer = self._setup_optimizer(
            cfg_optimizer=cfg.optimizer,
            optimizer_in_bwd=self._optimizer_in_bwd,
            opt_state_dict=(checkpoint_dict[training.OPT_KEY] if training.OPT_KEY in checkpoint_dict else None),
        )
        
        if self._resume_from_checkpoint:
            if self._enable_async_checkpointing:
                try:
                    checkpoint_dict = self._checkpoint_client.load_distributed_checkpoint(
                        self._model,
                        (self._optim_ckpt_wrapper if self._optimizer_in_bwd else self._optimizer),
                    )
                except Exception as e:
                    log.warning(f"Failed to load distributed checkpoint: {e}")
                    
            self._update_recipe_state(checkpoint_dict)
            
        # Initialize loss
        self._loss_fn = config.instantiate(cfg.loss)
        
        if self._compile:
            training.compile_loss(self._loss_fn, verbose=self._is_rank_zero)
            
        utils.log_rank_zero(log, "Loss initialized.")
        
        # Setup data
        collate_fn_component = cfg.get("collate_fn", "src.dataset.embedding_aware_collate_for_transformer_decoder")
        self._dataloader = self._setup_data(
            cfg_dataset=cfg.dataset,
            shuffle=cfg.shuffle,
            batch_size=cfg.batch_size,
            collate_fn_component=collate_fn_component,
        )
        
        # Update recipe state
        self._steps_per_epoch = len(self._dataloader) // self._gradient_accumulation_steps
        if self.max_steps_per_epoch is not None and self.max_steps_per_epoch < self._steps_per_epoch:
            self._steps_per_epoch = self.max_steps_per_epoch
            
        self.global_step = self.epochs_run * self._steps_per_epoch
        
        # Setup lr scheduler
        self._lr_scheduler = self._setup_lr_scheduler(
            cfg_lr_scheduler=cfg.get("lr_scheduler", None),
            num_training_steps=self.total_epochs * self._steps_per_epoch,
            last_epoch=self.global_step - 1,
        )
        
        # Set up profiler
        self._profiler = self._setup_profiler(cfg.get(PROFILER_KEY, None))
        
        # Used to ignore labels for loss computation
        self.ignore_labels_cache = torch.full(
            (cfg.batch_size, 1), self._loss_fn.ignore_index, device=self._device
        )
        
    def _setup_model(
        self,
        cfg_model: DictConfig,
        input_embedding_dim: int,
        num_embedding_tokens: int,
        enable_activation_checkpointing: bool,
        enable_activation_offloading: bool,
        fsdp_cpu_offload: bool,
        reshard_after_forward: bool,
        model_state_dict: Dict[str, Any],
        custom_sharded_layers: Optional[List[str]] = None,
        ac_mode: Optional[str] = None,
        ac_option: Optional[int] = None,
    ) -> nn.Module:
        """Sets up the model with embedding transformation layer."""
        utils.log_rank_zero(log, "Setting up distributed model...")
        init_start = time.perf_counter()
        
        # Create base model
        with training.set_default_dtype(self._dtype), torch.device("meta"):
            base_model = config.instantiate(cfg_model)
        
        # Wrap with embedding adapter
        wrapped_model = EmbeddingPromptFullModel(
            base_model=base_model,
            input_embedding_dim=input_embedding_dim,
            tokenizer=self._tokenizer,
            num_embedding_tokens=num_embedding_tokens
        )
        
        if self._compile:
            training.compile_model(wrapped_model, verbose=self._is_rank_zero)
            
        # Initialize device mesh
        device_mesh = init_device_mesh(
            self._device.type,
            mesh_shape=(self.data_parallel_dim, self.tensor_parallel_dim),
            mesh_dim_names=("dp", "tp"),
        )
        self.dp_size = device_mesh["dp"].size()
        self.dp_rank = device_mesh["dp"].get_local_rank()
        
        # Materialize the base model from meta device
        wrapped_model.base_model = wrapped_model.base_model.to_empty(device=self._device)
        
        # Initialize the mapping layer
        wrapped_model.materialize_mapping_layer(self._device)
        
        # Apply tensor parallelism
        if self.tensor_parallel_dim > 1:
            base_model_for_tp = wrapped_model.base_model
            
            with training.set_default_dtype(self._dtype), self._device:
                for m in base_model_for_tp.modules():
                    if hasattr(m, "rope_init"):
                        m.rope_init()
            
            base_model_for_tp = training.prepare_mha_for_tp(base_model_for_tp, device_mesh["tp"])
            parallelize_module(
                module=base_model_for_tp,
                device_mesh=device_mesh["tp"],
                parallelize_plan=self.tensor_parallel_plan,
            )
            log.info("Applied Tensor Parallelism.")
            
        # Apply activation checkpointing
        if enable_activation_checkpointing and ac_mode is None:
            training.set_activation_checkpointing(
                wrapped_model.base_model, auto_wrap_policy={modules.TransformerSelfAttentionLayer}
            )
        elif not enable_activation_checkpointing and ac_mode is not None:
            apply_selective_activation_checkpointing(wrapped_model.base_model, ac_mode, ac_option)
            
        # Apply FSDP
        if self.data_parallel_dim > 1:
            training.validate_no_params_on_meta_device(wrapped_model)
            
            fsdp_shard_conditions = [
                partial(training.get_shard_conditions, names_to_match=custom_sharded_layers)
            ]
            training.shard_model(
                model=wrapped_model,
                shard_conditions=fsdp_shard_conditions,
                cpu_offload=fsdp_cpu_offload,
                reshard_after_forward=reshard_after_forward,
                dp_mesh=device_mesh["dp"],
            )
            log.info(f"Applied FSDP with DP Dim: {self.data_parallel_dim}")
        else:
            if not isinstance(wrapped_model, nn.Module) or next(wrapped_model.parameters(), None) is None:
                wrapped_model = wrapped_model.to(self._device)
            log.info("DP dimension is 1, FSDP not applied.")
            
        # Initialize non-meta parameters
        with training.set_default_dtype(self._dtype), self._device:
            for m in wrapped_model.base_model.modules():
                if hasattr(m, "rope_init"):
                    m.rope_init()
                
        # Load state dict
        if model_state_dict:
            is_fsdp = isinstance(wrapped_model, torch.distributed.fsdp.FullyShardedDataParallel)
            adapted_state_dict = {"base_model." + k: v for k, v in model_state_dict.items()}
            
            if is_fsdp:
                if self.tensor_parallel_dim > 1:
                    training.load_from_full_model_state_dict(
                        wrapped_model, adapted_state_dict, self._device, strict=False, cpu_offload=fsdp_cpu_offload
                    )
                else:
                    load_policy = torch.distributed.fsdp.FullStateDictConfig(
                        offload_to_cpu=fsdp_cpu_offload, rank0_only=True
                    )
                    with torch.distributed.fsdp.FullyShardedDataParallel.state_dict_type(
                        wrapped_model, torch.distributed.fsdp.StateDictType.FULL_STATE_DICT, load_policy
                    ):
                        full_state_dict_cpu = adapted_state_dict if self._is_rank_zero else {}
                        wrapped_model.load_state_dict(full_state_dict_cpu, strict=False)
            else:
                try:
                    training.load_from_full_model_state_dict(wrapped_model, adapted_state_dict, self._device, strict=False)
                except Exception as e:
                    print(f"Fallback to direct load: {e}")
                    wrapped_model.load_state_dict(adapted_state_dict, strict=False)
        else:
            print("No base model state dict provided.")
            
        # Setup activation offloading
        self.activations_handling_ctx = training.get_act_offloading_ctx_manager(
            wrapped_model.base_model, enable_activation_offloading
        )
        
        training.validate_no_params_on_meta_device(wrapped_model)
        
        utils.log_rank_zero(log, f"Model setup took {time.perf_counter() - init_start:.2f} seconds")
        
        if self._is_rank_zero:
            memory_stats = training.get_memory_stats(device=self._device)
            training.log_memory_stats(memory_stats)
            
        torch.distributed.barrier()
        return wrapped_model
        
    def _setup_optimizer(
        self,
        cfg_optimizer: DictConfig,
        optimizer_in_bwd: bool = False,
        opt_state_dict: Optional[Dict[str, Any]] = None,
    ) -> Optional[Optimizer]:
        """Set up the optimizer."""
        if optimizer_in_bwd:
            optim_dict = {
                param: config.instantiate(cfg_optimizer, [param])
                for param in self._model.parameters() if param.requires_grad
            }
            training.register_optim_in_bwd_hooks(model=self._model, optim_dict=optim_dict)
            self._optim_ckpt_wrapper = training.create_optim_in_bwd_wrapper(model=self._model, optim_dict=optim_dict)
            
            if opt_state_dict is not None:
                try:
                    self._optim_ckpt_wrapper.load_state_dict(opt_state_dict)
                except Exception as e:
                    log.error(f"Failed to load optimizer_in_bwd state: {e}")
                    
            utils.log_rank_zero(log, "In-backward optimizers set up.")
            return None
        else:
            trainable_params = [p for p in self._model.parameters() if p.requires_grad]
            param_count = sum(p.numel() for p in trainable_params)
            print(f"Setting up optimizer for {param_count:,} trainable parameters.")
            
            optimizer = config.instantiate(cfg_optimizer, trainable_params)
            
            if opt_state_dict:
                try:
                    if isinstance(self._model, torch.distributed.fsdp.FullyShardedDataParallel):
                        full_osd = opt_state_dict if self._is_rank_zero else None
                        sharded_osd = torch.distributed.fsdp.FullyShardedDataParallel.scatter_full_optim_state_dict(
                            full_osd, self._model
                        )
                        optimizer.load_state_dict(sharded_osd)
                    else:
                        optimizer.load_state_dict(opt_state_dict)
                except Exception as e:
                    log.error(f"Failed to load optimizer state: {e}")
                    
            utils.log_rank_zero(log, "Optimizer initialized.")
            return optimizer
            
    def _setup_data(
        self,
        cfg_dataset: DictConfig,
        shuffle: bool,
        batch_size: int,
        collate_fn_component: str,
    ) -> DataLoader:
        """Set up the dataset and dataloader."""
        cfg_dataset_with_tokens = cfg_dataset.copy()
        cfg_dataset_with_tokens["num_embedding_tokens"] = self.num_embedding_tokens
        
        ds = config.instantiate(cfg_dataset_with_tokens, tokenizer=self._tokenizer)
        
        sampler = StatefulDistributedSampler(
            ds, num_replicas=self.dp_size, rank=self.dp_rank, shuffle=shuffle, seed=self.seed
        )
        
        try:
            collate_fn_builder = _get_component_from_path(collate_fn_component)
        except ImportError as e:
            raise ImportError(f"Could not import collate fn {collate_fn_component}: {e}")
            
        collate_fn = partial(
            collate_fn_builder, 
            tokenizer=self._tokenizer, 
            max_seq_len=cfg_dataset.max_seq_len,
            num_embedding_tokens=self.num_embedding_tokens
        )
        
        dataloader = DataLoader(
            dataset=ds,
            batch_size=batch_size,
            sampler=sampler,
            collate_fn=collate_fn,
            drop_last=True
        )
        
        utils.log_rank_zero(log, f"DataLoader: DP Size={self.dp_size}, Rank={self.dp_rank}")
        return dataloader
        
    def _setup_lr_scheduler(
        self,
        cfg_lr_scheduler: Optional[DictConfig],
        num_training_steps: int,
        last_epoch: int,
    ) -> Optional[Optimizer]:
        """Set up the learning rate scheduler."""
        if cfg_lr_scheduler is None:
            log.info("No LR scheduler configured.")
            return None
            
        optimizer = self._optimizer if not self._optimizer_in_bwd else next(iter(self._optim_ckpt_wrapper.optim_map.values()))
        
        lr_scheduler = config.instantiate(
            cfg_lr_scheduler, optimizer, num_training_steps=num_training_steps, last_epoch=last_epoch
        )
        
        if self._optimizer_in_bwd:
            self._optim_ckpt_wrapper.set_lr_scheduler(lr_scheduler)
            
        log.info("LR scheduler initialized.")
        return lr_scheduler
        
    def _setup_profiler(self, cfg_profiler: Optional[DictConfig] = None) -> Union[torch.profiler.profile, DummyProfiler]:
        """Set up the profiler."""
        if cfg_profiler is None:
            cfg_profiler = DictConfig({"enabled": False})
            
        if cfg_profiler.get("_component_", None) is None:
            cfg_profiler["_component_"] = "torchtune.training.setup_torch_profiler"
            
        profiler, profiler_cfg = config.instantiate(cfg_profiler)
        
        if self._is_rank_zero:
            self.profiler_profile_memory = profiler_cfg.get("profile_memory", False)
            if profiler_cfg["enabled"]:
                self.profiler_wait_steps = profiler_cfg["wait_steps"]
                self.profiler_warmup_steps = profiler_cfg["warmup_steps"]
                self.profiler_active_steps = profiler_cfg["active_steps"]
                
        return profiler
        
    def train(self) -> None:
        """Train the model."""
        training.cleanup_before_training()
        
        if not self._optimizer_in_bwd:
            self._optimizer.zero_grad()
        else:
            for opt in self._optim_ckpt_wrapper.optim_map.values():
                opt.zero_grad()
                
        t0 = time.perf_counter()
        running_loss = 0
        num_tokens = 0
        
        self._profiler.start()
        
        for curr_epoch in range(self.epochs_run, self.total_epochs):
            pbar = tqdm(total=self._steps_per_epoch, disable=not self._is_rank_zero, desc=f"Epoch {curr_epoch+1}")
            
            if isinstance(self._dataloader.sampler, StatefulDistributedSampler):
                self._dataloader.sampler.set_epoch(curr_epoch)
                
            self._model.train()
            
            for idx, batch in enumerate(self._dataloader):
                utils.batch_to_device(batch, self._device)

                labels = batch.pop("labels")
                current_num_tokens = (labels != self._loss_fn.ignore_index).sum()
                num_tokens += current_num_tokens

                batch_for_model = {
                    'input_embedding': batch['input_embedding'],
                    'input_ids': batch['input_ids'],
                    'mask': batch['mask'],
                    'insert_pos': batch['insert_pos']
                }

                with self.activations_handling_ctx:
                    try:
                        logits = self._model(**batch_for_model)

                        # Standard causal LM shift
                        shift_logits = logits[..., :-1, :].contiguous()
                        shift_labels = labels[..., 1:].contiguous()

                        if torch.isnan(shift_logits).any():
                            nan_percent = torch.isnan(shift_logits).float().mean().item() * 100
                            log.warning(f"NaN in logits ({nan_percent:.2f}%)")
                            continue

                        loss = self._loss_fn(
                            shift_logits.reshape(-1, shift_logits.size(-1)),
                            shift_labels.reshape(-1)
                        )
                    except Exception as e:
                        log.error(f"Forward/loss error at step {self.global_step}: {e}")
                        raise

                if torch.isnan(loss):
                    print(f"Skipping step {self.global_step} due to NaN loss")
                    if not self._optimizer_in_bwd:
                        self._optimizer.zero_grad(set_to_none=True)
                    continue

                current_loss_unnorm = loss * current_num_tokens
                running_loss += current_loss_unnorm

                loss_bw = loss / self._gradient_accumulation_steps if self._gradient_accumulation_steps > 1 else loss

                try:
                    loss_bw.backward()
                except Exception as e:
                    log.error(f"Backward error at step {self.global_step}: {e}")
                    raise
                    
                if (idx + 1) % self._gradient_accumulation_steps == 0:
                    total_loss = running_loss.clone().detach()
                    torch.distributed.all_reduce(total_loss)
                    
                    tokens_reduced = num_tokens.clone().detach()
                    torch.distributed.all_reduce(tokens_reduced)
                    
                    if tokens_reduced.item() < 1:
                        log.warning(f"Zero tokens at step {self.global_step}")
                        loss_log, grad_norm = 0.0, 0.0
                    else:
                        loss_log = total_loss.item() / tokens_reduced.item()
                        
                        if not self._optimizer_in_bwd:
                            if self._clip_grad_norm:
                                grad_norm = training.clip_grad_norm(self._model, self._clip_grad_norm)
                            else:
                                grad_norm = None
                            self._optimizer.step()
                            self._optimizer.zero_grad(set_to_none=True)
                        else:
                            grad_norm = None
                            
                    if self._lr_scheduler:
                        self._lr_scheduler.step()
                        
                    self.global_step += 1
                    pbar.update(1)
                    pbar.set_description(f"E{curr_epoch+1}|S{self.global_step}|L:{loss_log:.4f}")

                    # Debug printing
                    if self._is_rank_zero and self.global_step % (self._log_every_n_steps * 10) == 0:
                        self._print_debug_predictions(logits.detach(), labels.detach())
                    
                    # Log metrics
                    if self.global_step % self._log_every_n_steps == 0 and self._is_rank_zero:
                        step_time = (time.perf_counter() - t0) / self._log_every_n_steps
                        tokens_sec = tokens_reduced.item() / (step_time * self.world_size)
                        
                        log_dict = {
                            "loss": loss_log,
                            "lr": get_lr(self._optimizer if not self._optimizer_in_bwd else self._optim_ckpt_wrapper),
                            "tokens_per_second_per_gpu": tokens_sec,
                            "epoch": curr_epoch + 1
                        }
                        
                        if grad_norm is not None:
                            log_dict["grad_norm"] = grad_norm
                        if self._log_peak_memory_stats:
                            log_dict.update(training.get_memory_stats(device=self._device))
                            
                        self._metric_logger.log_dict(log_dict, step=self.global_step)
                        t0 = time.perf_counter()
                        
                    running_loss = 0
                    num_tokens = torch.tensor(0, device=self._device)
                    self._profiler.step()
                    
                if ((idx + 1) // self._gradient_accumulation_steps) >= self.max_steps_per_epoch:
                    break
                    
            self.epochs_run += 1
            
            # Save checkpoint
            self._checkpoint_client.save_checkpoint(
                model=self._model.base_model,
                optimizer=(self._optimizer if not self._optimizer_in_bwd else self._optim_ckpt_wrapper),
                training_progress=TrainingProgress(
                    seed=self.seed,
                    epochs_run=self.epochs_run,
                    total_epochs=self.total_epochs,
                    max_steps_per_epoch=self.max_steps_per_epoch,
                ),
                epoch=curr_epoch,
            )

            if self._is_rank_zero:
                print(f"Checkpoint saved for epoch {curr_epoch}")

            # Save mapping layer separately
            self._save_mapping_layer(curr_epoch)
            torch.distributed.barrier()
            
        self._profiler.stop()
        log.info("Training finished.")
        
    def _print_debug_predictions(self, logits: torch.Tensor, labels: torch.Tensor) -> None:
        """Print debug predictions vs labels."""
        try:
            predicted_ids = torch.argmax(logits, dim=-1)
            labels_sample = labels[0].cpu()
            predicted_ids_sample = predicted_ids[0].cpu()
            
            valid_indices = torch.where(labels_sample != self._loss_fn.ignore_index)[0]
            
            if len(valid_indices) > 0:
                start_idx = valid_indices[0].item()
                end_idx = valid_indices[-1].item() + 1
                
                actual_ids = labels_sample[start_idx:end_idx].tolist()
                predicted_ids_list = predicted_ids_sample[start_idx:end_idx].tolist()
                
                actual_text = self._tokenizer.decode(actual_ids, skip_special_tokens=False)
                predicted_text = self._tokenizer.decode(predicted_ids_list, skip_special_tokens=False)
                
                print(f"\
{'='*60}")
                print(f"DEBUG @ Step {self.global_step}")
                print(f"ACTUAL ({len(actual_ids)} tokens): {actual_text}")
                print(f"PREDICTED ({len(predicted_ids_list)} tokens): {predicted_text}")
                print(f"{'='*60}\
")
        except Exception as e:
            print(f"Debug printing error: {e}")
            
    def _save_mapping_layer(self, epoch: int) -> None:
        """Save the mapping FFN layer separately."""
        mapping_layer_path = os.path.join(self._output_dir, f"mapping_layer_epoch_{epoch}.pt")
        
        is_fsdp = isinstance(self._model, torch.distributed.fsdp.FullyShardedDataParallel)
        
        if is_fsdp:
            with torch.distributed.fsdp.FullyShardedDataParallel.state_dict_type(
                self._model,
                torch.distributed.fsdp.StateDictType.FULL_STATE_DICT,
                torch.distributed.fsdp.FullStateDictConfig(offload_to_cpu=True, rank0_only=True)
            ):
                if self._is_rank_zero:
                    try:
                        full_state_dict = self._model.state_dict()
                        module_instance = self._model.module if hasattr(self._model, 'module') else self._model
                        
                        ffn_state_dict = {}
                        for k, v in full_state_dict.items():
                            if "mapping_ffn" in k:
                                # Save RELATIVE keys (e.g. "0.weight") with NO "mapping_ffn."
                                # prefix, so the checkpoint loads directly into
                                # EmbeddingMapper.mapping_ffn via mapping_ffn.load_state_dict()
                                # at inference time (query_decoder/grammar_constrained_inference.py).
                                relative_key = k.split("mapping_ffn.")[-1] if "mapping_ffn." in k else k
                                ffn_state_dict[relative_key] = v.full_tensor() if isinstance(v, DTensor) else v
                        
                        mapping_layer_state = {
                            "input_embedding_dim": module_instance.input_embedding_dim,
                            "hidden_dim": module_instance.hidden_dim,
                            "ffn_hidden_dim": module_instance.ffn_hidden_dim,
                            "num_embedding_tokens": module_instance.num_embedding_tokens,
                            "mapping_ffn": ffn_state_dict,
                            "model_dtype": str(module_instance.model_dtype)
                        }
                        
                        torch.save(mapping_layer_state, mapping_layer_path)
                        log.info(f"Mapping FFN saved to {mapping_layer_path}")
                    except Exception as e:
                        log.error(f"Error saving mapping FFN: {e}")
        else:
            if self._is_rank_zero:
                try:
                    module_instance = self._model
                    ffn_state_dict = {}
                    
                    for k, v in module_instance.mapping_ffn.state_dict().items():
                        # Keys are already relative (e.g. "0.weight"); store with NO
                        # "mapping_ffn." prefix so they load directly into
                        # EmbeddingMapper.mapping_ffn at inference time.
                        ffn_state_dict[k] = v.full_tensor() if isinstance(v, DTensor) else v
                    
                    mapping_layer_state = {
                        "input_embedding_dim": module_instance.input_embedding_dim,
                        "hidden_dim": module_instance.hidden_dim,
                        "ffn_hidden_dim": module_instance.ffn_hidden_dim,
                        "num_embedding_tokens": module_instance.num_embedding_tokens,
                        "mapping_ffn": ffn_state_dict,
                        "model_dtype": str(module_instance.model_dtype)
                    }
                    
                    torch.save(mapping_layer_state, mapping_layer_path)
                    log.info(f"Mapping FFN saved to {mapping_layer_path}")
                except Exception as e:
                    log.error(f"Error saving mapping FFN: {e}")
            
    def cleanup(self) -> None:
        """Clean up resources after training."""
        if self._is_rank_zero and hasattr(self, '_metric_logger') and self._metric_logger:
            self._metric_logger.close()
            
        if torch.distributed.is_initialized():
            destroy_process_group()


@config.parse
def recipe_main(cfg: DictConfig) -> None:
    """Entry point for the embedding fine-tuning recipe."""
    config.log_config(recipe_name="EmbeddingFinetuneRecipe", cfg=cfg)
    
    recipe = EmbeddingFinetuneRecipe(cfg=cfg)
    recipe.setup(cfg=cfg)
    recipe.train()
    recipe.cleanup()


if __name__ == "__main__":
    try:
        recipe_main()
    except Exception as e:
        print(f"Recipe execution failed: {e}")
        import traceback
        traceback.print_exc()
        if torch.distributed.is_initialized():
            destroy_process_group()
        sys.exit(1)
    sys.exit(0)