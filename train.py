import os

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from sklearn.model_selection import StratifiedKFold

from utils import create_dir
from evaluate import evaluate_fn
from metrics import metrics_report
from radam import RAdam
from data import FraudDataset

def train_one_epoch(model, dataloader, optim, criterion, device='cpu'):
    loss_sum = 0
    model.train() 
    for x, y in dataloader:
        output = model(x.to(device))
        loss   = criterion(output, y.to(device))
        optim.zero_grad()
        loss.backward()
        optim.step()
        loss_sum += loss.item()
    return loss_sum/len(dataloader)

def train(model, train_loader, valid_loader, optim, criterion,
            n_epochs=10, save_epochs=1, output_dir='model/', device='cpu', verbose=False):
    create_dir(output_dir)
    train_losses, valid_losses = [], []
    f1s = []
    best_f1 = -1
    best_epoch = 0
    for epoch in range(n_epochs):
        train_loss = train_one_epoch(model, train_loader, optim, criterion, device)
        valid_loss,tn,fp,fn,tp,precision,recall,f1Score = evaluate_fn(model, valid_loader, criterion, 
                                                                            device, verbose=verbose)

        # Acumulando as perdas de treino e validação
        train_losses.append(train_loss)
        valid_losses.append(valid_loss)
        f1s.append(f1Score)

        if f1Score > best_f1:
            best_f1 = f1Score
            best_epoch = epoch + 1

        if epoch % save_epochs == 0:
            save_path = os.path.join(output_dir, f'epoch_{epoch+1}.pth')
            torch.save(model.state_dict(), save_path)

        if verbose:
            print(('ep: [{}/{}] -- T: {:.5} -- V: {:.5} -- F1: {:.5}').format(epoch+1, n_epochs, train_loss, valid_loss, f1Score))
    return best_f1, best_epoch

def perform_kfold_cv(df, models, optims, criterion, k_folds, n_epochs=10, random_state=1, output_dir='kfold/', device='cpu', batch_size=100):
    assert len(models) == len(optims) == k_folds
    create_dir(output_dir)
    skf = StratifiedKFold(n_splits=k_folds, random_state=random_state, shuffle=True)
    folds_f1s = []

    for fold, (train_index, eval_index) in enumerate(skf.split(np.zeros(df.shape[0]), df.flag)):
        print(('--- K Fold [{}/{}] ---').format(fold+1,k_folds))

        save_dir = os.path.join(output_dir, f'fold_{fold+1}')
        # Iniciando a totalização das perdas por fold
        perdas_treino_fold = 0

        X_train, X_eval = df.to_numpy()[train_index,:-1], df.to_numpy()[eval_index,:-1]
        y_train, y_eval = df.flag.to_numpy()[train_index], df.flag.to_numpy()[eval_index]

        dataset_train = FraudDataset(X_train,y_train)        
        dataset_eval = FraudDataset(X_eval,y_eval)

        ########Train
        train_loader = DataLoader(dataset=dataset_train, batch_size=batch_size, shuffle=True)
        ########Valid 
        valid_loader = DataLoader(dataset=dataset_eval, batch_size=batch_size, shuffle=False)                        
        
        model = models[fold]
        optim = optims[fold]

        best_f1, best_epoch = train(model, train_loader, valid_loader, optim, criterion, n_epochs, output_dir=save_dir, verbose=True, device=device)
        print(f'Fold {fold+1} got F1 = {best_f1} at epoch {best_epoch}')
        folds_f1s.append((best_f1, best_epoch, train_index, eval_index))

        ## Load best checkpoint
        model.load_state_dict(torch.load(os.path.join(output_dir, f'fold_{fold+1}', f'epoch_{best_epoch}.pth')))
        print('Printing report at best checkpoint for F1')
        metrics_report(model, valid_loader, device=device)

    return folds_f1s

