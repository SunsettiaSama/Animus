from delegate.config import DelegateConfig, DelegateProfile
from delegate.manager import DelegateManager
from delegate.result import DelegateResult

# Backward-compatible aliases
SubAgentConfig  = DelegateConfig
SubAgentProfile = DelegateProfile
SubAgentManager = DelegateManager
SubAgentResult  = DelegateResult

__all__ = [
    "DelegateConfig",
    "DelegateProfile",
    "DelegateManager",
    "DelegateResult",
    # aliases
    "SubAgentConfig",
    "SubAgentProfile",
    "SubAgentManager",
    "SubAgentResult",
]
