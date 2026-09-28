"""Transport-independent object contract and explicitly composed module registry."""
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class Capability(BaseModel):
    type: str
    writable: bool = False
    unit: str | None = None
    minimum: float | None = None
    maximum: float | None = None


class HubObject(BaseModel):
    id: str
    module: str
    type: str
    name: str
    available: bool
    state: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Capability] = Field(default_factory=dict)
    actions: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(min_length=1, max_length=80)
    value: Any


class ObjectModule(Protocol):
    id: str

    def describe(self) -> dict: ...
    def objects(self) -> list[HubObject]: ...
    def act(self, object_id: str, request: ActionRequest) -> dict: ...


class ModuleRegistry:
    def __init__(self):
        self.modules: dict[str, ObjectModule] = {}

    def register(self, module: ObjectModule):
        if module.id in self.modules:
            raise ValueError("Duplicate module")
        self.modules[module.id] = module

    def descriptions(self):
        result = []
        for module in self.modules.values():
            try:
                result.append(module.describe())
            except Exception:
                result.append({"id": module.id, "status": "error"})
        return result

    def objects(self, module_id=None):
        result = []
        for module in self.modules.values():
            if module_id is not None and module.id != module_id:
                continue
            try:
                result.extend(module.objects())
            except Exception:
                # The modules endpoint carries availability; one provider cannot
                # prevent discovery of objects from other providers.
                continue
        return result

    def get(self, object_id):
        module = self.modules.get(object_id.partition(".")[0])
        if module is None:
            raise HTTPException(404, "Object not found")
        try:
            obj = next((obj for obj in module.objects() if obj.id == object_id), None)
        except Exception:
            raise HTTPException(503, "Module unavailable") from None
        if obj is None:
            raise HTTPException(404, "Object not found")
        return module, obj


def object_router(registry: ModuleRegistry, require_auth):
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_auth)])

    @router.get("/modules")
    def modules():
        return {"modules": registry.descriptions()}

    @router.get("/objects")
    def objects(module: str | None = None):
        return {"objects": registry.objects(module)}

    @router.get("/objects/{object_id}", response_model=HubObject)
    def object_detail(object_id: str):
        return registry.get(object_id)[1]

    @router.post("/objects/{object_id}/actions", status_code=202)
    def action(object_id: str, request: ActionRequest):
        module, obj = registry.get(object_id)
        if request.action not in obj.actions:
            raise HTTPException(422, "Unsupported action")
        try:
            return module.act(object_id, request)
        except KeyError:
            raise HTTPException(404, "Object not found") from None
        except ValueError:
            raise HTTPException(422, "Invalid action value") from None
        except Exception:
            raise HTTPException(503, "Module unavailable or command not sent") from None

    return router
