"""Train the improved HOG + multinomial logistic thermal emotion classifier."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from ml.data import discover, extract_hog


def train(args):
    rows = discover(args.dataset, 'thermal')
    seen, features, targets, corrupt = set(), [], [], []
    for path, label in rows:
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            features.append(extract_hog(raw))
            targets.append(label)
        except (OSError, SyntaxError) as exc:
            corrupt.append({'path': str(path), 'error': str(exc)})

    x, y = np.asarray(features), np.asarray(targets)
    train_ids, test_ids = train_test_split(
        np.arange(len(y)), test_size=.2, stratify=y, random_state=args.seed)
    evaluation_model = LogisticRegression(
        C=args.c, max_iter=3000, class_weight='balanced', random_state=args.seed)
    evaluation_model.fit(x[train_ids], y[train_ids])
    predicted = evaluation_model.predict(x[test_ids])
    labels = evaluation_model.classes_.tolist()
    accuracy = float(accuracy_score(y[test_ids], predicted))

    # Refit the deployed classifier on every usable image after the fixed holdout evaluation.
    deployed_model = LogisticRegression(
        C=args.c, max_iter=3000, class_weight='balanced', random_state=args.seed)
    deployed_model.fit(x, y)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output / 'model_v2.npz',
        coef=deployed_model.coef_.astype(np.float32),
        intercept=deployed_model.intercept_.astype(np.float32),
        labels=deployed_model.classes_,
        model_name=np.asarray('thermal-hog-logreg-v2'))
    metrics = {
        'trained_at': datetime.now(timezone.utc).isoformat(),
        'model': 'thermal-hog-logreg-v2',
        'features': 'HOG: 16x16 blocks, 8x8 cells, 9 orientations on 96x96 CLAHE grayscale',
        'classifier': 'multinomial logistic regression; C=' + str(args.c),
        'total_images': int(len(y)),
        'original_images': len(rows),
        'duplicate_or_unreadable_images': len(rows) - len(y),
        'class_counts': dict(Counter(targets)),
        'split_method': 'fixed stratified 80/20 image split; seed=' + str(args.seed),
        'evaluation_train_images': int(len(train_ids)),
        'held_out_test_images': int(len(test_ids)),
        'held_out_test_accuracy': accuracy,
        'test_accuracy': accuracy,
        'splits': {'train': int(len(train_ids)), 'validation': 0, 'test': int(len(test_ids))},
        'duplicate_images': len(rows) - len(y) - len(corrupt),
        'corrupt_images': corrupt,
        'history': [],
        'report': classification_report(y[test_ids], predicted, labels=labels,
                                        output_dict=True, zero_division=0),
        'confusion_matrix': confusion_matrix(y[test_ids], predicted, labels=labels).tolist(),
        'labels': labels,
        'deployment_training_images': int(len(y)),
        'training_history': [{
            'trained_at': datetime.now(timezone.utc).isoformat(),
            'total_images': int(len(y)),
            'test_accuracy': accuracy,
            'split_method': 'fixed stratified 80/20 image split; seed=' + str(args.seed)
        }],
        'limitations': 'Image-level split may include the same participant in training and test. Validate on subject-disjoint data before claiming person-independent performance.'
    }
    (output / 'metrics_v2.json').write_text(json.dumps(metrics, indent=2))
    print(json.dumps({'held_out_test_accuracy': accuracy, 'artifact': str(output/'model_v2.npz')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='C:/Users/suhas/Downloads/dataset/trainit')
    parser.add_argument('--output', default='ml/artifacts')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--c', type=float, default=10.0)
    train(parser.parse_args())
