from .experience import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceBuilder,
    ExperienceCollapser,
    ExperienceFeeling,
    ExperienceLog,
    ExperienceSituation,
    ExperienceUnit,
    NullCollapser,
)
from .orchestrator import ExperienceOrchestrator, MemoryIngestPort
from .chronicle import ChronicleEntry, ChronicleKind, ChronicleStore
from .journal import (
    DiceResult,
    JournalStore,
    K_RECENT_LANDMARKS,
    Landmark,
    LandmarkFiller,
    LandmarkStatus,
    LifeJournal,
    MAX_DAILY_LANDMARKS,
    NullLandmarkFiller,
    roll_d100,
)
from .service import LifeService
from .manager import LifeManager
from .block import JournalBlock, LifeProfileBlock

__all__ = [
    # ── Experience layer ──────────────────────────────────────────────────────
    "ExperienceUnit",
    "ExperienceAction",
    "ExperienceActionKind",
    "ExperienceFeeling",
    "ExperienceSituation",
    "ExperienceLog",
    "ExperienceBuilder",
    "ExperienceCollapser",
    "NullCollapser",
    # ── Orchestration ─────────────────────────────────────────────────────────
    "ExperienceOrchestrator",
    "MemoryIngestPort",
    # ── Chronicle ─────────────────────────────────────────────────────────────
    "ChronicleEntry",
    "ChronicleKind",
    "ChronicleStore",
    # ── Journal (手账) ─────────────────────────────────────────────────────────
    "DiceResult",
    "roll_d100",
    "Landmark",
    "LandmarkStatus",
    "LandmarkFiller",
    "NullLandmarkFiller",
    "MAX_DAILY_LANDMARKS",
    "K_RECENT_LANDMARKS",
    "LifeJournal",
    "JournalStore",
    # ── Service ───────────────────────────────────────────────────────────────
    "LifeService",
    # ── Legacy / tao.py contract ──────────────────────────────────────────────
    "LifeManager",
    "LifeProfileBlock",
    "JournalBlock",
]
