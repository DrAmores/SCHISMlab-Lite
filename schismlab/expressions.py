"""Expresiones numericas en el YAML: numeros o cadenas evaluadas con numpy (p.ej. "15*cos(2*pi*lat/0.9)")."""
from __future__ import annotations
import ast
import numpy as np

_NS = {k: getattr(np, k) for k in ("sin", "cos", "tan", "exp", "log", "sqrt", "tanh", "sinh", "cosh",
                                  "abs", "where", "minimum", "maximum", "clip", "pi", "e", "sign", "arctan", "deg2rad")}
_NS["heaviside"] = lambda a: np.heaviside(a, 0.5)
_NS["gauss"] = lambda r, sigma: np.exp(-0.5 * (r / sigma) ** 2)


def is_expression(v) -> bool:
    return isinstance(v, str)


def uses(v, name: str) -> bool:
    """True si la expresion menciona la variable `name` (p.ej. 'z' o 't')."""
    import re
    return is_expression(v) and re.search(rf"\b{name}\b", v) is not None


_ALLOWED_NODES = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp, ast.IfExp, ast.Call, ast.Name, ast.Constant,
                  ast.Tuple, ast.List, ast.Load, ast.operator, ast.unaryop, ast.cmpop, ast.boolop, ast.keyword)
_ALLOWED_NAMES = set(_NS) | {"x", "y", "z", "lon", "lat", "depth", "h", "t"}


def validate(v: str, extra_names=None) -> None:
    """Comprueba que la expresión solo usa números, operadores, comparaciones y las funciones y variables permitidas.
    Rechaza atributos, índices, lambdas, nombres con guiones bajos, etc. (un YAML importado de un desconocido no debe poder
    ejecutar código). Lanza ValueError con un mensaje claro."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("expresión vacía")
    try:
        tree = ast.parse(v, mode="eval")
    except SyntaxError as ex:
        raise ValueError(f"expresión mal formada: {v!r} ({ex.msg})") from None
    allowed = _ALLOWED_NAMES if extra_names is None else set(_NS) | set(extra_names)   # con variables dadas: solo esas
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"expresión no permitida ({type(node).__name__}): {v!r}")
        if isinstance(node, ast.Name) and (node.id not in allowed or node.id.startswith("_")):
            raise ValueError(f"nombre desconocido en la expresión: {node.id!r} (permitidos: x, y, z, lon, lat, depth, h, t y funciones numpy básicas)")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _NS):
            raise ValueError(f"llamada no permitida en la expresión: {v!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, bool)):
            raise ValueError(f"constante no permitida en la expresión: {node.value!r}")


def evaluate(v, **vars):
    """Evalua `v` (numero o expresion) con las variables dadas (arrays numpy). Devuelve array/escalar."""
    if not is_expression(v):
        return np.asarray(v, float)
    validate(v, vars.keys())
    ns = dict(_NS); ns.update(vars)
    out = eval(compile(v, "<yaml>", "eval"), {"__builtins__": {}}, ns)  # noqa: S307 (validada con ast: solo aritmetica)
    return np.asarray(out, float)
