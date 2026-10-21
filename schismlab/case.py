"""Lectura del fichero YAML de un caso y acceso a sus secciones con valores por defecto."""
from __future__ import annotations
from pathlib import Path
import yaml


class Case:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.cfg = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        self.name = self.cfg.get("name", self.path.stem)
        self.dir = self.path.parent
        self.workdir = Path(self.cfg.get("workdir", self.dir / self.name)).expanduser()
        if not self.workdir.is_absolute():
            self.workdir = self.dir / self.workdir

    def section(self, key: str) -> dict:
        v = self.cfg.get(key)
        if v is None:
            raise KeyError(f"El caso '{self.name}' no tiene seccion '{key}'")
        return v
