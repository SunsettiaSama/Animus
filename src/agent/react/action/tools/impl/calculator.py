from __future__ import annotations

import ast
import math
import operator
from typing import ClassVar

from pydantic import BaseModel, Field

from ....action.base import BaseAction

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_SAFE_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": math.pi, "e": math.e,
    "ceil": math.ceil, "floor": math.floor,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op_fn = _SAFE_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"unsupported operator: {type(node.op).__name__}")
        return op_fn(_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op_fn = _SAFE_OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"unsupported unary operator: {type(node.op).__name__}")
        return op_fn(_safe_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple function calls are allowed")
        fn = _SAFE_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"unknown function: {node.func.id!r}")
        args = [_safe_eval(a) for a in node.args]
        return fn(*args)
    if isinstance(node, ast.Name):
        val = _SAFE_FUNCS.get(node.id)
        if val is None:
            raise ValueError(f"unknown name: {node.id!r}")
        return val
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


class CalculatorArgs(BaseModel):
    expression: str = Field(..., min_length=1, description="数学表达式，如 '2+3*4' 或 'sqrt(16)'")


class CalculatorAction(BaseAction):
    name: str = "calculator"
    description: str = (
        "计算数学表达式，支持四则运算、幂、取模、常用数学函数（sqrt/sin/cos/log等）。"
        "参数：expression（字符串，如 '2+3*4' 或 'sqrt(16)'）"
    )
    args_model: ClassVar[type[BaseModel]] = CalculatorArgs

    def execute(self, expression: str, **kwargs) -> str:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expression} = {result}"
