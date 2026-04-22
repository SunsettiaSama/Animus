from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction

_LENGTH: dict[str, float] = {
    "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
    "mile": 1609.344, "yard": 0.9144, "foot": 0.3048, "ft": 0.3048,
    "inch": 0.0254, "in": 0.0254, "nm": 1e-9,
}

_WEIGHT: dict[str, float] = {
    "kg": 1.0, "g": 0.001, "mg": 1e-6, "t": 1000.0,
    "lb": 0.453592, "oz": 0.0283495,
    "jin": 0.5, "liang": 0.05,
}

_AREA: dict[str, float] = {
    "m2": 1.0, "km2": 1e6, "cm2": 1e-4, "mm2": 1e-6,
    "ha": 1e4, "acre": 4046.856,
    "mu": 666.667,
}

_SPEED: dict[str, float] = {
    "m/s": 1.0, "km/h": 1/3.6, "mph": 0.44704, "knot": 0.514444,
}

_FAMILIES = [_LENGTH, _WEIGHT, _AREA, _SPEED]
_UNIT_NAMES = {
    "m": "米", "km": "千米", "cm": "厘米", "mm": "毫米",
    "mile": "英里", "yard": "码", "foot": "英尺", "ft": "英尺",
    "inch": "英寸", "in": "英寸", "nm": "纳米",
    "kg": "千克", "g": "克", "mg": "毫克", "t": "吨",
    "lb": "磅", "oz": "盎司", "jin": "斤", "liang": "两",
    "m2": "平方米", "km2": "平方千米", "cm2": "平方厘米",
    "ha": "公顷", "acre": "英亩", "mu": "亩",
    "m/s": "米/秒", "km/h": "千米/时", "mph": "英里/时", "knot": "节",
}


def _convert(value: float, from_unit: str, to_unit: str) -> float:
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()
    for family in _FAMILIES:
        if from_unit in family and to_unit in family:
            return value * family[from_unit] / family[to_unit]
    if from_unit in ("c", "celsius") and to_unit in ("f", "fahrenheit"):
        return value * 9 / 5 + 32
    if from_unit in ("f", "fahrenheit") and to_unit in ("c", "celsius"):
        return (value - 32) * 5 / 9
    if from_unit in ("c", "celsius") and to_unit in ("k", "kelvin"):
        return value + 273.15
    if from_unit in ("k", "kelvin") and to_unit in ("c", "celsius"):
        return value - 273.15
    raise ValueError(f"不支持从 {from_unit!r} 到 {to_unit!r} 的单位转换")


class UnitConverterArgs(BaseModel):
    value: float = Field(..., description="要换算的数值")
    from_unit: str = Field(..., min_length=1, description="原单位")
    to_unit: str = Field(..., min_length=1, description="目标单位")


class UnitConverterAction(BaseAction):
    name: str = "unit_converter"
    description: str = (
        "单位换算。参数：value（数值），from_unit（原单位），to_unit（目标单位）。"
        "支持长度(m/km/cm/mm/mile/foot/inch)、重量(kg/g/lb/oz/jin)、"
        "面积(m2/km2/ha/mu/acre)、速度(m/s/km/h/mph)、温度(C/F/K)"
    )
    args_model: ClassVar[type[BaseModel]] = UnitConverterArgs

    def execute(self, value: float, from_unit: str, to_unit: str, **kwargs) -> str:
        result = _convert(float(value), from_unit, to_unit)
        fu = _UNIT_NAMES.get(from_unit.lower(), from_unit)
        tu = _UNIT_NAMES.get(to_unit.lower(), to_unit)
        formatted = f"{result:.6g}"
        result_str = formatted.rstrip("0").rstrip(".") if "." in formatted else formatted
        return f"{value} {fu} = {result_str} {tu}"
