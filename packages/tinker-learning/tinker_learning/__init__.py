"""tinker-learning: record demonstrations, a deterministic baseline (replay + parametric template, NOT ML),
genuine behavior cloning (PyTorch, exported to ONNX), a model registry, and approved retraining with rollback."""
from .recorder import Recorder, InvalidDemonstration, demo_series
from .baseline import ParametricTemplate, replay
from .registry import ModelRegistry, RegistryError
from .runtime import SkillRuntime, BCPolicy

__version__ = "0.1.0"
__all__ = ["Recorder", "InvalidDemonstration", "demo_series", "ParametricTemplate", "replay",
           "ModelRegistry", "RegistryError", "SkillRuntime", "BCPolicy"]
