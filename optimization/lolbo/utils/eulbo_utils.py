import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
import torch
import math
import copy 
from torch.utils.data import TensorDataset, DataLoader
import gpytorch
from botorch.acquisition.analytic import ExpectedImprovement
from botorch.acquisition import qExpectedImprovement
from botorch.acquisition.analytic import LogExpectedImprovement
from botorch.acquisition.logei import qLogExpectedImprovement
from gpytorch.mlls import MarginalLogLikelihood
from torch.autograd import Variable 
from gpytorch.utils.quadrature import GaussHermiteQuadrature1D
from torch.quasirandom import SobolEngine
from botorch.generation.sampling import MaxPosteriorSampling
from linear_operator.operators import TriangularLinearOperator
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
softplus_func = torch.nn.Softplus()


def update_model_elbo(
    model,
    train_x,
    train_y,
    mll=None,
    lr=0.01,
    n_epochs=30,
    train_bsz=32,
    grad_clip=1.0,
    normed_best_f=None,
    train_to_convergence=True, 
    max_allowed_n_failures_improve_loss=10,
    max_allowed_n_epochs=100,
):
    if mll is None:
        mll = gpytorch.mlls.VariationalELBO(model.likelihood, model, num_data=train_x.size(-2))
    model.train()
    optimizer = torch.optim.Adam([{'params': model.parameters(), 'lr': lr} ], lr=lr)
    train_bsz = min(len(train_y),train_bsz)
    train_dataset = TensorDataset(train_x, train_y)
    train_loader = DataLoader(train_dataset, batch_size=train_bsz, shuffle=True)

    lowest_loss = torch.inf 
    n_failures_improve_loss = 0
    epochs_trained = 0
    continue_training_condition = True 
    # for _ in range(n_epochs):
    while continue_training_condition:
        total_loss = 0
        for (inputs, scores) in train_loader:
            optimizer.zero_grad()
            output = model(inputs.to(device))
            loss = -mll(output, scores.to(device))
            loss.backward()
            if grad_clip is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=grad_clip)
            optimizer.step()
            total_loss += loss.item()
        epochs_trained += 1
        if total_loss < lowest_loss:
            lowest_loss = total_loss
        else:
            n_failures_improve_loss += 1
        if train_to_convergence:
            continue_training_condition = n_failures_improve_loss < max_allowed_n_failures_improve_loss
            if epochs_trained > max_allowed_n_epochs:
                continue_training_condition = False 
        else:
            continue_training_condition = epochs_trained < n_epochs

    model.eval()
            
    return_dict = {}
    return_dict["model"] = model 
    return return_dict


def update_model_and_generate_candidates_eulbo(
    model,
    train_x, # list of selfies 
    train_z, # latent space points tensor 
    train_y, # scores tensor 
    censoring, 
    objective,
    lb, 
    ub,
    update_e2e_w_vae,
    mll=None,
    lr=0.01,
    n_epochs=30,
    train_bsz=64,
    grad_clip=2.0,
    normed_best_f=None,
    acquisition_bsz=1,
    train_to_convergence=True, 
    max_allowed_n_failures_improve_loss=10,
    max_allowed_n_epochs=100,
    init_x_next=None,
    x_next_lr=0.001,
    alternate_updates=True, 
    use_turbo=False, 
    alternate_updates_every_n_epochs=1,
    num_kg_samples=64, 
    use_kg=False, # if True, do knowledge gradient instead of ei 
    dtype=torch.float64,
    num_mc_samples_qei=64,
):
    if torch.is_tensor(lb):
        lb = lb.to(device)
        ub = ub.to(device)

    if update_e2e_w_vae:
        return_dict = e2e_update_model_and_vae_and_generate_candidates_jointly(
            model=model,
            train_x=train_x,
            train_y=train_y,
            censoring=censoring,
            lb=lb, 
            ub=ub,
            objective=objective, # added for lolbo (contains VAE as object)
            init_x_next=init_x_next,
            mll=mll,
            lr=lr,
            x_next_lr=x_next_lr,
            n_epochs=n_epochs,
            train_bsz=train_bsz,
            normed_best_f=normed_best_f,
            acquisition_bsz=acquisition_bsz,
            grad_clip=grad_clip,
            train_to_convergence=train_to_convergence,
            max_allowed_n_failures_improve_loss=max_allowed_n_failures_improve_loss,
            max_allowed_n_epochs=max_allowed_n_epochs,
            alternate_updates=alternate_updates,
            alternate_updates_every_n_epochs=alternate_updates_every_n_epochs,
            num_kg_samples=num_kg_samples, 
            use_kg=use_kg, # if True, do knowledge gradient instead of ei 
            dtype=dtype,
            num_mc_samples_qei=num_mc_samples_qei,
        )
    else:
        return_dict = update_model_and_generate_candidates_jointly(
            model=model,
            train_x=train_z,
            train_y=train_y,
            censoring=censoring,
            mll=mll,
            lr=lr,
            x_next_lr=x_next_lr,
            n_epochs=n_epochs,
            train_bsz=train_bsz,
            normed_best_f=normed_best_f,
            acquisition_bsz=acquisition_bsz,
            init_x_next=init_x_next,
            grad_clip=grad_clip,
            train_to_convergence=train_to_convergence,
            max_allowed_n_failures_improve_loss=max_allowed_n_failures_improve_loss,
            max_allowed_n_epochs=max_allowed_n_epochs,
            alternate_updates=alternate_updates,
            lb=lb, 
            ub=ub,
            alternate_updates_every_n_epochs=alternate_updates_every_n_epochs,
            num_kg_samples=num_kg_samples, 
            use_kg=use_kg, # if True, do knowledge gradient instead of ei 
            dtype=dtype,
            num_mc_samples_qei=num_mc_samples_qei,
        )

    return return_dict


def get_q_expected_log_utility_ei(
    model,
    best_f,
    x_next, # (q,d)
    base_samples,
    num_mc_samples=64,
):
    # x_next.shape # torch.Size([3, 6]) (q, d)
    output = model(x_next) # q-dim multivariate normal #
    # use MC sampling 
    # samples = output.rsample(torch.Size([num_mc_samples])) # (S, q) 
    samples = output.rsample(torch.Size([num_mc_samples]), base_samples=base_samples) # torch.Size([64, 3]) (S, q)
    # compute log utility of each sample 
    log_utilities = torch.log(softplus_func(samples - best_f)) # (S, q) of utilities for each sample  torch.Size([64, 3])
    # max over q dimension, mean over s dimension to get final expected_log_utility
    expected_log_utility = log_utilities.amax(-1) # (S,) torch.Size([64]) 
    # expected_log_utility = expected_log_utility.mean() # tensor(-4.0313, device='cuda:0', grad_fn=<MeanBackward0>) # remove, mean happens for all in main trianing loop 
    return expected_log_utility 

def get_expected_log_utility_ei(
    model,
    best_f,
    x_next, # (q,d)
):
    output = model(x_next) 
    def log_utility(y,):
        # compute log utility based on y and best_f
        log_utility = torch.log(softplus_func(y - best_f)) 
        return log_utility.to(device)
    
    ghq = GaussHermiteQuadrature1D()
    ghq = ghq.to(device)
    expected_log_utility = ghq(log_utility, output)
            
    return expected_log_utility


def update_model_and_generate_candidates_jointly(
    model,
    train_x,
    train_y,
    censoring,
    lb,
    ub,
    init_x_next=None,
    mll=None,
    lr=0.01,
    x_next_lr=0.001,
    n_epochs=30,
    train_bsz=32,
    normed_best_f=None,
    acquisition_bsz=1,
    grad_clip=2.0,
    train_to_convergence=True, 
    max_allowed_n_failures_improve_loss=10,
    max_allowed_n_epochs=100,
    alternate_updates=True,
    alternate_updates_every_n_epochs=1,
    num_kg_samples=64, # S in notes
    use_kg=False, # if True, do knowledge gradient instead of ei 
    dtype=torch.float64,
    num_mc_samples_qei=64,
):
    torch.autograd.set_detect_anomaly(True) # Should give helpful info in stack trce if training fails 
    if mll is None:
        mll = gpytorch.mlls.VariationalELBO(model.likelihood, model, num_data=train_x.size(-2))
    model.train() 
    if init_x_next is None:
        init_x_next = torch.rand(acquisition_bsz, train_x.shape[-1], requires_grad=True)*(ub - lb) + lb # torch.Size([10, 60])
    init_x_next = init_x_next.to(device=device)
    x_next = Variable(init_x_next, requires_grad=True)
    x_next_optimizer = torch.optim.Adam([{'params': x_next},], lr=x_next_lr)
    model_params_to_update = model.parameters()

    model_optimizer = torch.optim.Adam([{'params': model_params_to_update, 'lr':lr} ], lr=lr)
    joint_optimizer = torch.optim.Adam([{'params': x_next,},{'params': model_params_to_update, 'lr':lr} ], lr=lr)

    if use_kg:
        # Use ts to initialize kg_samples 
        thompson_sampling = MaxPosteriorSampling(
            model=model,
            replacement=False,
        ) 
        dim = train_x.shape[-1]
        n_ts_candidates = min(5000, max(2000, 200 * dim)) # from TuRBO ts 
        sobol = SobolEngine(dim, scramble=True) 
        ts_x_cands = sobol.draw(n_ts_candidates).to(device=device).to(dtype=dtype)
        ts_x_cands = ts_x_cands*(ub - lb) + lb # (n_ts_candidates, dim)
        with torch.no_grad():
            kg_samples = thompson_sampling(ts_x_cands, num_samples=num_kg_samples ) # (num_kg_samples, dim) 
        kg_samples = torch.clone(kg_samples.detach()).requires_grad_(True).to(device=device)
        # Initialize random zs 
        if acquisition_bsz == 1:
            zs = torch.randn(num_kg_samples, requires_grad=True, device=device) 
        else:
            zs = torch.randn(num_kg_samples, x_next.shape[0], requires_grad=True, device=device) # (num_kg_samples, q)
    else:
        kg_samples = None
        zs = None 
    
    base_samples = torch.randn(num_mc_samples_qei, acquisition_bsz).to(device=device).to(dtype=dtype) 
    
    train_bsz = min(len(train_y),train_bsz)
    if len(train_y.shape) > 1:
        train_y = train_y.squeeze()
    train_dataset = TensorDataset(train_x, train_y, censoring)
    train_loader = DataLoader(train_dataset, batch_size=train_bsz, shuffle=True)

    switch_dict = {}
    switch_dict[True] = False
    switch_dict[False] = True
    currently_training_model = True 
    
    lowest_loss = torch.inf 
    n_failures_improve_loss = 0
    epochs_trained = 0
    continue_training_condition = True 
    if (max_allowed_n_epochs == 0) or (n_epochs == 0):
        continue_training_condition = False 

    while continue_training_condition:
        total_loss = 0
        for (inputs, scores, censoring_batch) in train_loader:
            if alternate_updates:
                model_optimizer.zero_grad()
                x_next_optimizer.zero_grad()
            else:
                joint_optimizer.zero_grad()
            if len(inputs) == 1:
                # NOTE: hack to handle case with only one training data point 
                inputs = torch.cat((inputs, inputs))
                scores = torch.cat((scores, scores))
                censoring_batch = torch.cat((censoring_batch, censoring_batch))
            output = model(inputs.to(device))
            nelbo = -mll(output, scores.to(device), censoring=censoring_batch.to(device))
            expected_log_utility_x_next = get_expected_log_utility_x_next(
                use_kg=use_kg,
                acquisition_bsz=acquisition_bsz,
                model=model,
                x_next=x_next,
                kg_samples=kg_samples,
                zs=zs,
                normed_best_f=normed_best_f,
                base_samples=base_samples,
                num_mc_samples_qei=num_mc_samples_qei,
            )
            loss = nelbo - expected_log_utility_x_next
            loss.backward()
            if grad_clip is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=grad_clip)
                torch.nn.utils.clip_grad_norm_(x_next, max_norm=grad_clip)
            if alternate_updates:
                if currently_training_model: 
                    model_optimizer.step() 
                else:
                    x_next_optimizer.step()
            else:
                joint_optimizer.step()
            with torch.no_grad():   
                x_next[:,:] = x_next.clamp(lb, ub) 
                total_loss += loss.item()
        epochs_trained += 1
        if epochs_trained % alternate_updates_every_n_epochs == 0:
            currently_training_model = switch_dict[currently_training_model]
        if total_loss < lowest_loss:
            lowest_loss = total_loss
        else:
            n_failures_improve_loss += 1
        if train_to_convergence:
            continue_training_condition = n_failures_improve_loss < max_allowed_n_failures_improve_loss
            if epochs_trained > max_allowed_n_epochs:
                continue_training_condition = False 
        else:
            continue_training_condition = epochs_trained < n_epochs
    model = model.eval()

    return_dict = {}
    return_dict["model"] = model 
    return_dict["x_next"] = x_next.detach().cpu()  

    return return_dict


def get_expected_log_utility_x_next(
    use_kg,
    acquisition_bsz,
    model,
    x_next,
    kg_samples,
    zs,
    normed_best_f,
    base_samples,
    num_mc_samples_qei,
):
    if use_kg:
        if acquisition_bsz == 1:
            expected_log_utility_x_next = get_expected_log_utility_knowledge_gradient(
                model=model,
                x_next=x_next, 
                kg_samples=kg_samples, 
                zs=zs,
                normed_best_f=normed_best_f, 
            ) 
        else:
            expected_log_utility_x_next = get_q_expected_log_utility_knowledge_gradient(
                model=model,
                x_next=x_next, 
                kg_samples=kg_samples, 
                zs=zs,
                normed_best_f=normed_best_f, 
            ) 
    else:
        if acquisition_bsz == 1:
            expected_log_utility_x_next = get_expected_log_utility_ei( 
                model=model, 
                best_f=normed_best_f, 
                x_next=x_next,
            )
        else: 
            expected_log_utility_x_next = get_q_expected_log_utility_ei(
                model=model, 
                best_f=normed_best_f, 
                x_next=x_next,
                base_samples=base_samples,
                num_mc_samples=num_mc_samples_qei,
            )

    return expected_log_utility_x_next.mean()


def get_turbo_lb_ub(ub, lb, X, Y, tr_length):
    if lb is None:
        lb = X.min().item() 
    if ub is None:
        ub = X.max().item()
    x_center = copy.deepcopy(X[Y.argmax(), :]) 
    weights = torch.ones_like(x_center)
    weights = weights * (ub - lb)
    tr_lb = torch.clamp(x_center - weights * tr_length / 2.0, lb, ub) 
    tr_ub = torch.clamp(x_center + weights * tr_length / 2.0, lb, ub) 
    return tr_lb.to(device), tr_ub.to(device) 


def get_q_expected_log_utility_knowledge_gradient(model, x_next, kg_samples, zs, normed_best_f):
    x_next_pred = model(x_next)
    y_samples = x_next_pred.rsample(torch.Size([kg_samples.shape[0]]), base_samples=zs) + x_next_pred.stddev*zs # (num_kg_samples,q) (S,q) torch.Size([64, 3])
    chol_factor = model.variational_strategy._cholesky_factor(None) # (M,M)  torch.Size([100, 100])
    U = model.covar_module(model.variational_strategy.inducing_points, x_next) # (M,q) torch.Size([100, q]), torch.Size([100, 3])
    S = model.covar_module(x_next, x_next, diag=True) # K(x_next, x_next), torch.Size(q), torch.Size([3])
    chol_factor_tensor = chol_factor._tensor.tensor # (M,M) = torch.Size([100, 100])
    chol_factor_tensor_repeated = chol_factor_tensor.repeat(x_next.shape[0], 1, 1,) # (q, M, M), torch.Size([3, 100, 100])
    L = torch.cat((chol_factor_tensor_repeated, torch.zeros(x_next.shape[0], chol_factor_tensor.shape[-1], 1).to(device)), -1) # (q, M, M+1), torch.Size([3, 100, 101])
    var_mean = chol_factor @ model.variational_strategy.variational_distribution.mean
    var_mean = var_mean.repeat(x_next.shape[0],1).unsqueeze(-1) # (q,M,1), torch.Size([3, 100, 1])
    var_mean_repeated = var_mean.repeat(1,1,y_samples.shape[-2]) # (q,M,num_kg_samples), torch.Size([3, 100, 64])
    y_samples_reshaped = y_samples.reshape(y_samples.shape[-1], y_samples.shape[-2]) # torch.Size([3, 64]) (q,S)
    y_samples_reshaped = y_samples_reshaped.unsqueeze(-2) # torch.Size([3, 1, 64]) (q,1,S)
    var_mean_repeated = torch.cat((var_mean_repeated, y_samples_reshaped), -2) # (q,M+1,num_kg_samples), torch.Size([3, 101, 64])
    L_12 = chol_factor.solve(U.evaluate_kernel().tensor) # (M,q), torch.Size([100, 3])
    L_12_mt = L_12.mT.unsqueeze(-1) # (q,M,1), torch.Size([3, 100, 1])
    schur_complement = S - (L_12_mt * L_12_mt).squeeze(-1).sum(-1) # (q,), torch.Size([3])
    schur_complement = schur_complement.unsqueeze(-1).unsqueeze(-1) # (q,1,1), torch.Size([3, 1, 1])
    L_22 = schur_complement.to_dense()**0.5  # (q,1,1), torch.Size([3, 1, 1])
    L_temp = torch.cat((L_12_mt, L_22), -2) # (q, M+1, 1) , torch.Size([3, 101, 1])
    L_temp_reshaped = L_temp.squeeze().unsqueeze(-2) # torch.Size([3, 1, 101]) 
    L = torch.cat((L, L_temp_reshaped), -2) # (q, M+1, M+1), torch.Size([3, 101, 101])
    L = TriangularLinearOperator(L) 
    alphas = L._transpose_nonbatch().solve(L.solve(var_mean_repeated)) # (q, M+1, S), torch.Size([3, 101, 64])
    x_next_temp = x_next.unsqueeze(-2) # (q,1,d), torch.Size([3, 1, 6])
    q_Zs = model.variational_strategy.inducing_points.repeat(x_next.shape[0],1,1) # (q,M,d), torch.Size([3, 100, 6])
    inducing_points_and_x_next = torch.cat((q_Zs, x_next_temp), -2) # (q, M+1, D), torch.Size([3, 101, 6])
    constant_mean = model.mean_module.constant # torch.Size([]), tensor(-0.0017, device='cuda:0', requires_grad=True)
    pred_mean_each_x_sample = model.covar_module(kg_samples, inducing_points_and_x_next) # (q, S, M+1), torch.Size([3, 64, 101])
    pred_mean_each_x_sample = pred_mean_each_x_sample * alphas.mT # torch.Size([3, 64, 101])
    pred_mean_each_x_sample = pred_mean_each_x_sample.sum(-1) + constant_mean # (q,S) , torch.Size([3, 64])
    expected_log_utility_kg = torch.log(softplus_func(pred_mean_each_x_sample - normed_best_f)) # (q, S,) , torch.Size([3, 64])
    expected_log_utility_kg = expected_log_utility_kg.amax(-2) # (S,) # torch.Size([64])
    
    return expected_log_utility_kg 




def get_expected_log_utility_knowledge_gradient(model, x_next, kg_samples, zs, normed_best_f):
    x_next_pred = model(x_next)
    y_samples = x_next_pred.mean + x_next_pred.stddev*zs # (num_kg_samples,)
    y_samples = y_samples.unsqueeze(-2) # (1, num_kg_samples) = (1,S)
    chol_factor = model.variational_strategy._cholesky_factor(None) # (M,M)  torch.Size([100, 100])
    U = model.covar_module(model.variational_strategy.inducing_points, x_next) # (M,1) torch.Size([100, 1])
    S = model.covar_module(x_next, x_next) # K(x_next, x_next) = torch.Size([1, 1])
    chol_factor_tensor = chol_factor._tensor.tensor # (M,M) = torch.Size([100, 100])
    L = torch.cat((chol_factor_tensor, torch.zeros(chol_factor_tensor.shape[-1], 1).to(device)), -1) # (M, M+1) torch.Size([100, 101])
    var_mean = chol_factor @ model.variational_strategy.variational_distribution.mean
    var_mean = var_mean.unsqueeze(-1) # (M,1) # torch.Size([100, 1])
    var_mean_repeated = var_mean.repeat(1,y_samples.shape[-1]) # (M,num_kg_samples) = (M,S) = torch.Size([100, 64])
    var_mean_repeated = torch.cat((var_mean_repeated, y_samples)) # (M+1,num_kg_samples) = (M+1, S) = torch.Size([101, 64])
    L_12 = chol_factor.solve(U.evaluate_kernel().tensor) # (M,1) = torch.Size([100, 1]) 
    schur_complement = S - L_12.mT @ L_12 # torch.Size([1, 1])
    L_22 = schur_complement.to_dense()**0.5  # torch.Size([1, 1])
    L_temp = torch.cat((L_12, L_22), -2) # (M+1, 1) = torch.Size([101, 1])
    L_temp = L_temp.squeeze().unsqueeze(-2) # Shape should be (1, M+1) = torch.Size([1, 101])
    L = torch.cat((L, L_temp), -2) # (M+1, M+1) = torch.Size([101, 101])
    L = TriangularLinearOperator(L) 
    alphas = L._transpose_nonbatch().solve(L.solve(var_mean_repeated)) # (M+1, S) = torch.Size([101, 64])
    inducing_points_and_x_next = torch.cat((model.variational_strategy.inducing_points, x_next), -2) # (M+1, D) = torch.Size([101, 6])
    constant_mean = model.mean_module.constant # torch.Size([]), tensor(-0.0508, device='cuda:0', requires_grad=True)
    pred_mean_each_x_sample = model.covar_module(kg_samples, inducing_points_and_x_next) # (S, M+1) = (num_kg_samples, M+1) =  torch.Size([3, 101])
    pred_mean_each_x_sample = pred_mean_each_x_sample * alphas.mT 
    pred_mean_each_x_sample = pred_mean_each_x_sample.sum(-1) + constant_mean # (S,) torch.Size([3])
    expected_log_utility_kg = torch.log(softplus_func(pred_mean_each_x_sample - normed_best_f)) # (S,) torch.Size([3])

    return expected_log_utility_kg


# start w/ udpate jointly, add vae stuff 
def e2e_update_model_and_vae_and_generate_candidates_jointly(
    model,
    train_x,
    train_y,
    lb,
    ub,
    objective, # added for lolbo (contains VAE as object)
    init_x_next=None,
    mll=None,
    lr=0.01,
    x_next_lr=0.001,
    n_epochs=30,
    train_bsz=32,
    normed_best_f=None,
    acquisition_bsz=1,
    grad_clip=2.0,
    train_to_convergence=True, 
    max_allowed_n_failures_improve_loss=10,
    max_allowed_n_epochs=100,
    alternate_updates=True,
    alternate_updates_every_n_epochs=1,
    num_kg_samples=64, # S in notes
    use_kg=False, # if True, do knowledge gradient instead of ei 
    dtype=torch.float64,
    num_mc_samples_qei=64,
):
    objective.vae.train() # added for lolbo

    torch.autograd.set_detect_anomaly(True) # Should give helpful info in stack trce if training fails 
    if mll is None:
        mll = gpytorch.mlls.VariationalELBO(model.likelihood, model, num_data=len(train_x))
    model.train() 
    if init_x_next is None:
        init_x_next = torch.rand(acquisition_bsz, objective.dim, requires_grad=True)*(ub - lb) + lb # torch.Size([10, 60])
    init_x_next = init_x_next.to(device=device)
    x_next = Variable(init_x_next, requires_grad=True)

    x_next_optimizer = torch.optim.Adam([{'params': x_next},], lr=x_next_lr)
    model_optimizer = torch.optim.Adam([{'params': objective.vae.parameters()}, {'params': model.parameters(), 'lr':lr} ], lr=lr)
    joint_optimizer = torch.optim.Adam([{'params': x_next,}, {'params': objective.vae.parameters()}, {'params': model.parameters(), 'lr':lr} ], lr=lr)

    if use_kg:
        # Use ts to initialize kg_samples 
        thompson_sampling = MaxPosteriorSampling(
            model=model,
            replacement=False,
        ) 
        dim = objective.dim
        n_ts_candidates = min(5000, max(2000, 200 * dim)) # from TuRBO ts 
        sobol = SobolEngine(dim, scramble=True) 
        ts_x_cands = sobol.draw(n_ts_candidates).to(device=device).to(dtype=dtype)
        ts_x_cands = ts_x_cands*(ub - lb) + lb # (n_ts_candidates, dim)
        with torch.no_grad():
            kg_samples = thompson_sampling(ts_x_cands, num_samples=num_kg_samples ) # (num_kg_samples, dim) 
        kg_samples = torch.clone(kg_samples.detach()).requires_grad_(True).to(device=device)
        # Initialize random zs 
        if acquisition_bsz == 1:
            zs = torch.randn(num_kg_samples, requires_grad=True, device=device) 
        else:
            zs = torch.randn(num_kg_samples, x_next.shape[0], requires_grad=True, device=device) # (num_kg_samples, q)
    else:
        kg_samples = None
        zs = None 
    
    base_samples = torch.randn(num_mc_samples_qei, acquisition_bsz).to(device=device).to(dtype=dtype) 
    
    
    train_bsz = min(len(train_y),train_bsz)
    
    # NOTE: NO LONGER WORKS WITH TRAIN_X BEING A LIST
    # train_dataset = TensorDataset(train_x, train_y)
    # train_loader = DataLoader(train_dataset, batch_size=train_bsz, shuffle=True)

    switch_dict = {}
    switch_dict[True] = False
    switch_dict[False] = True
    currently_training_model = True 
    
    lowest_loss = torch.inf 
    n_failures_improve_loss = 0
    epochs_trained = 0
    continue_training_condition = True 
    if (max_allowed_n_epochs == 0) or (n_epochs == 0):
        continue_training_condition = False 

    num_batches = math.ceil(len(train_x) / train_bsz)
    while continue_training_condition:
        total_loss = 0
        # for (inputs, scores) in train_loader:
        for batch_ix in range(num_batches):
            if alternate_updates:
                model_optimizer.zero_grad()
                x_next_optimizer.zero_grad()
            else:
                joint_optimizer.zero_grad()
            
            start_idx, stop_idx = batch_ix*train_bsz, (batch_ix+1)*train_bsz
            batch_x_list = train_x[start_idx:stop_idx]
            batch_z, vae_loss = objective.vae_forward(batch_x_list)
            batch_y = train_y[start_idx:stop_idx]
            if not torch.is_tensor(batch_y):
                batch_y = torch.tensor(batch_y).float() 

            output = model(batch_z.to(device))
            nelbo = -mll(output, batch_y.to(device))
            expected_log_utility_x_next = get_expected_log_utility_x_next(
                use_kg=use_kg,
                acquisition_bsz=acquisition_bsz,
                model=model,
                x_next=x_next,
                kg_samples=kg_samples,
                zs=zs,
                normed_best_f=normed_best_f,
                base_samples=base_samples,
                num_mc_samples_qei=num_mc_samples_qei,
            )
            loss = vae_loss + nelbo - expected_log_utility_x_next
            loss.backward()
            if grad_clip is not None:
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=grad_clip)
                torch.nn.utils.clip_grad_norm_(x_next, max_norm=grad_clip)
                torch.nn.utils.clip_grad_norm_(objective.vae.parameters(), max_norm=grad_clip)
            if alternate_updates:
                if currently_training_model: 
                    model_optimizer.step() 
                else:
                    x_next_optimizer.step()
            else:
                joint_optimizer.step()
            with torch.no_grad():   
                x_next[:,:] = x_next.clamp(lb, ub) 
                total_loss += loss.item()
        epochs_trained += 1
        if epochs_trained % alternate_updates_every_n_epochs == 0:
            currently_training_model = switch_dict[currently_training_model]
        if total_loss < lowest_loss:
            lowest_loss = total_loss
        else:
            n_failures_improve_loss += 1
        if train_to_convergence:
            continue_training_condition = n_failures_improve_loss < max_allowed_n_failures_improve_loss
            if epochs_trained > max_allowed_n_epochs:
                continue_training_condition = False 
        else:
            continue_training_condition = epochs_trained < n_epochs

    model = model.eval()
    objective.vae.eval()

    return_dict = {}
    return_dict["model"] = model 
    return_dict["x_next"] = x_next.detach().cpu()  
    return_dict["objective"] = objective

    return return_dict