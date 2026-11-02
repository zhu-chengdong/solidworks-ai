"""Module dispatch is separate from model providers and CAD transport."""
from dataclasses import dataclass

from .settings import UserFacingError


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    inputs: tuple[str, ...]
    engine: object


class ModuleRegistry:
    def __init__(self, modules):
        self.modules = {}
        for item in modules:
            if item.id in self.modules:
                raise ValueError("Duplicate module id")
            self.modules[item.id] = item

    def require(self, module_id):
        if module_id not in self.modules:
            raise UserFacingError("该科研模块尚未安装。")
        return self.modules[module_id]

    def public(self):
        return [{"id": m.id, "title": m.title, "inputs": list(m.inputs)} for m in self.modules.values()]
