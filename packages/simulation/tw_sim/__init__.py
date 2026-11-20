"""simulation: headless deterministic MuJoCo checks for tinker trajectories (not the host geometry engine)."""
from .mj import SimConfig, build_mjcf, simulate, sunlit_fraction

__version__ = "0.1.0"
__all__ = ["SimConfig", "build_mjcf", "simulate", "sunlit_fraction"]
