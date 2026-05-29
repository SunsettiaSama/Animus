import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_agent = sys.modules.setdefault("agent", types.ModuleType("agent"))
_agent.__path__ = [str(SRC / "agent")]
_soul = types.ModuleType("agent.soul")
_soul.__path__ = [str(SRC / "agent" / "soul")]
_soul.__package__ = "agent.soul"
sys.modules["agent.soul"] = _soul

import importlib.util

def _load(name: str, rel: str):
    path = SRC / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_enums = _load(
    "agent.soul.memory.domain.enums",
    "agent/soul/memory/domain/enums.py",
)
_emotion = _load(
    "agent.soul.memory.emotion_intensity",
    "agent/soul/memory/emotion_intensity.py",
)
_node = _load(
    "agent.soul.memory.graph.networks.event.node",
    "agent/soul/memory/graph/networks/event/node.py",
)
FactualMemory = _node.FactualMemory
infer_emotion_intensity = _emotion.infer_emotion_intensity
node_emotion_intensity = _emotion.node_emotion_intensity


def test_infer_from_subjective_and_emotion_label():
    intensity = infer_emotion_intensity(
        "难过",
        "我今天特别难过，心里堵得�?,
    )
    assert intensity >= 0.52


def test_infer_calm_subjective_maps_low():
    intensity = infer_emotion_intensity(
        "平静",
        "我在午后阳光里继续整理笔记，心里很安�?,
    )
    assert 0.15 <= intensity <= 0.35


def test_node_emotion_intensity_uses_perception():
    node = FactualMemory(
        focus="整理笔记",
        fact="raw",
        perception="我欣喜若狂地完成了一�?,
        emotion="开�?,
        emotion_intensity=0.1,
    )
    assert node_emotion_intensity(node) >= 0.52
    assert node.activation() > 0.5
