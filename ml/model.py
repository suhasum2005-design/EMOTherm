import torch
from torch import nn


class ThermalCNN(nn.Module):
    """Small single-channel CNN suitable for an academic CPU demo."""
    def __init__(self, classes):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 16, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(16, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool2d((4, 4)))
        self.head = nn.Sequential(nn.Flatten(), nn.Dropout(.25), nn.Linear(1024, classes))

    def forward(self, x):
        return self.head(self.features(x))
