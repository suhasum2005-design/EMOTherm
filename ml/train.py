"""Run from the project root: python -m ml.train --dataset <path>."""
import argparse
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.model_selection import train_test_split, GroupShuffleSplit
from torch.utils.data import TensorDataset, DataLoader
from ml.data import discover, preprocess
from ml.model import ThermalCNN


def train(args):
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)
    rows = discover(args.dataset, args.modality)
    seen, kept, corrupt = {}, [], []
    for path, label in rows:
        try:
            raw = path.read_bytes()
            h = hashlib.sha256(raw).hexdigest()
            if h in seen:
                if seen[h] != label:
                    raise ValueError('Identical image assigned to different labels: ' + str(path))
                continue
            array = preprocess(raw)
            seen[h] = label
            kept.append((path, label, array))
        except (OSError, SyntaxError) as exc:
            corrupt.append({'path': str(path), 'error': str(exc)})
    labels = sorted({label for _, label, _ in kept})
    y = np.array([labels.index(label) for _,label,_ in kept])
    x = np.stack([a for _,_,a in kept])[:,None,:,:]
    indices = np.arange(len(y))
    if args.subject_regex:
        pattern = re.compile(args.subject_regex)
        groups = []
        for path,_,_ in kept:
            match = pattern.search(path.name)
            if match is None:
                raise ValueError('Subject regex must match every image filename: ' + path.name)
            groups.append(match.group(1))
        groups = np.array(groups)
        splitter = GroupShuffleSplit(n_splits=1, test_size=.2, random_state=args.seed)
        trainval, test = next(splitter.split(indices, y, groups))
        splitter = GroupShuffleSplit(n_splits=1, test_size=.25, random_state=args.seed)
        train_local, val_local = next(splitter.split(trainval, y[trainval], groups[trainval]))
        train_ids, val = trainval[train_local], trainval[val_local]
        split_method = 'subject-group-disjoint'
    else:
        trainval, test = train_test_split(indices, test_size=.2, stratify=y, random_state=args.seed)
        train_ids, val = train_test_split(trainval, test_size=.25, stratify=y[trainval], random_state=args.seed)
        split_method = 'stratified-image; subject overlap unknown'
    for name, ids in [('train', train_ids), ('validation', val), ('test', test)]:
        if len(set(y[ids])) != len(labels):
            raise ValueError(f'{name} split lacks a class. Use a different seed or more subjects.')
    def loader(ids, shuffle=False):
        return DataLoader(TensorDataset(torch.from_numpy(x[ids]), torch.from_numpy(y[ids]).long()), batch_size=args.batch_size, shuffle=shuffle)
    model = ThermalCNN(len(labels))
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    counts = np.bincount(y[train_ids], minlength=len(labels))
    loss_fn = torch.nn.CrossEntropyLoss(weight=torch.tensor(len(train_ids)/(len(labels)*counts), dtype=torch.float32))
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    history, best = [], float('inf')
    def evaluate(ids):
        model.eval()
        losses, predicted, actual = [], [], []
        with torch.inference_mode():
            for inputs, targets in loader(ids):
                scores = model(inputs)
                losses.append(float(loss_fn(scores, targets)))
                predicted.extend(scores.argmax(1).tolist())
                actual.extend(targets.tolist())
        return float(np.mean(losses)), accuracy_score(actual, predicted), actual, predicted
    for epoch in range(args.epochs):
        model.train()
        total, correct, loss_total = 0, 0, 0
        for inputs, targets in loader(train_ids, True):
            # Horizontal flips preserve broad face geometry; no RGB/thermal mixing.
            if random.random() < .5:
                inputs = inputs.flip(-1)
            optimizer.zero_grad()
            scores = model(inputs)
            loss = loss_fn(scores, targets)
            loss.backward()
            optimizer.step()
            total += len(targets)
            correct += int((scores.argmax(1) == targets).sum())
            loss_total += float(loss.detach()) * len(targets)
        val_loss, val_accuracy, _, _ = evaluate(val)
        row = dict(epoch=epoch+1, loss=loss_total/total, accuracy=correct/total, val_loss=val_loss, val_accuracy=val_accuracy)
        history.append(row)
        print(json.dumps(row), flush=True)
        if val_loss < best:
            best = val_loss
            torch.save({'state_dict': model.state_dict(), 'labels': labels, 'image_size': 96}, output/'model.next.pt')
    model.load_state_dict(torch.load(output/'model.next.pt', weights_only=True)['state_dict'])
    _, accuracy, actual, predicted = evaluate(test)
    report = classification_report(actual, predicted, labels=list(range(len(labels))), target_names=labels, output_dict=True, zero_division=0)
    metrics = dict(trained_at=datetime.now(timezone.utc).isoformat(), labels=labels, total_images=len(kept),
        original_images=len(rows), duplicate_images=len(rows)-len(kept)-len(corrupt), corrupt_images=corrupt,
        class_counts=dict(Counter(label for _,label,_ in kept)), split_method=split_method,
        splits={'train':len(train_ids),'validation':len(val),'test':len(test)}, seed=args.seed,
        test_accuracy=accuracy, report=report, confusion_matrix=confusion_matrix(actual,predicted,labels=list(range(len(labels)))).tolist(), history=history)
    (output/'metrics.json').write_text(json.dumps(metrics, indent=2))
    split_manifest = {name:[str(kept[int(i)][0]) for i in ids] for name,ids in [('train',train_ids),('validation',val),('test',test)]}
    (output/'split_manifest.json').write_text(json.dumps(split_manifest,indent=2))
    prior = json.loads((output/'training_history.json').read_text()) if (output/'training_history.json').exists() else []
    prior.append({k:metrics[k] for k in ['trained_at','total_images','test_accuracy','split_method']})
    (output/'training_history.json').write_text(json.dumps(prior,indent=2))
    from ml.plots import export
    export(output)
    (output/'model.next.pt').replace(output/'model.pt')
    print('Held-out test accuracy:',accuracy, flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset', default='C:/Users/suhas/Downloads/dataset/trainit')
    parser.add_argument('--modality', choices=['thermal','visible','all'], default='thermal')
    parser.add_argument('--epochs', type=int, default=20)
    parser.add_argument('--batch-size',type=int,default=32)
    parser.add_argument('--threads',type=int,default=2)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--subject-regex', help='Filename regex with capture group 1 = subject ID; recommended for report evaluation')
    parser.add_argument('--output',default='ml/artifacts')
    train(parser.parse_args())
