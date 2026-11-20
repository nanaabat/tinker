"""connector-sdk: the host adapter interface every 3D host implements, capability negotiation, and a mock host."""
from .base import HostConnector, Capabilities, negotiate, ConnectorError
from .mock import MockHost
from .pushed import PushedSceneConnector

__version__ = "0.1.0"
__all__ = ["HostConnector", "Capabilities", "negotiate", "ConnectorError", "MockHost", "PushedSceneConnector"]
