import io
import re
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff'}


def preprocess(raw, size=96):
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img).convert('L')
        a = np.array(img)
    a = cv2.GaussianBlur(a, (3, 3), 0)
    a = cv2.normalize(a, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    a = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(a)
    return cv2.resize(a, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32) / 255


def extract_hog(raw, size=96):
    """Extract shape/edge features from the same normalized thermal input used by the UI."""
    image = (preprocess(raw, size) * 255).astype(np.uint8)
    hog = cv2.HOGDescriptor((size, size), (16, 16), (8, 8), (8, 8), 9)
    return hog.compute(image).reshape(-1).astype(np.float32)


def discover(root, modality='thermal'):
    """Accept simple class folders and this user's nested TI/th versus VI/vi folders."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f'Dataset directory does not exist: {root}')
    rows = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        label = re.sub(r'^\d+[.\s_-]*', '', folder.name).strip()
        label = re.sub(r'\s+F$', '', label, flags=re.I).lower().replace(' ', '_')
        for path in sorted(folder.rglob('*')):
            if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                continue
            parts = [p.lower() for p in path.relative_to(folder).parts[:-1]]
            visible = any(p == 'vi' or p.endswith(' vi') for p in parts)
            thermal = any(p == 'ti' or p.endswith(' th') for p in parts)
            if modality == 'thermal' and visible:
                continue
            if modality == 'visible' and thermal:
                continue
            rows.append((path, label))
    if not rows:
        raise ValueError('No supported images found for the selected modality.')
    return rows
