from pathlib import Path
import threading
import numpy as np
import torch
from ml.model import ThermalCNN
from ml.data import preprocess, extract_hog


class Predictor:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.model = None
        self.stamp = None

    def predict(self, raw):
        if not self.path.exists():
            raise FileNotFoundError('No trained model. Run python -m ml.train first.')
        with self.lock:
            stamp = self.path.stat().st_mtime_ns
            if self.model is None or stamp != self.stamp:
                if self.path.suffix.lower() == '.npz':
                    bundle = np.load(self.path, allow_pickle=False)
                    self.labels = [str(v) for v in bundle['labels'].tolist()]
                    self.model = {
                        'coef': bundle['coef'].astype(np.float32),
                        'intercept': bundle['intercept'].astype(np.float32),
                    }
                    self.model_name = str(bundle['model_name'].item())
                    self.stamp = stamp
                else:
                    # Load tensor state and primitive metadata only, never arbitrary pickled models.
                    bundle = torch.load(self.path, map_location='cpu', weights_only=True)
                    self.labels = bundle['labels']
                    self.model = ThermalCNN(len(self.labels))
                    self.model.load_state_dict(bundle['state_dict'])
                    self.model.eval()
                    self.model_name = 'thermal-cnn-v1'
                    self.stamp = stamp
            if isinstance(self.model, dict):
                features = extract_hog(raw)
                logits = self.model['coef'] @ features + self.model['intercept']
                logits -= logits.max()
                values = (np.exp(logits) / np.exp(logits).sum()).tolist()
            else:
                with torch.inference_mode():
                    x = torch.from_numpy(preprocess(raw)).unsqueeze(0).unsqueeze(0)
                    values = torch.softmax(self.model(x), 1)[0].tolist()
        probabilities = dict(zip(self.labels, values))
        return {'emotion': max(probabilities, key=probabilities.get), 'confidence': max(values),
                'probabilities': probabilities, 'model': self.model_name}
