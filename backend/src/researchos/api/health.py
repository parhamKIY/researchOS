from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/health", tags=["health"])


class HealthRead(BaseModel):
    status: Literal["ok", "unavailable"]


@router.get("/live", response_model=HealthRead)
def live() -> HealthRead:
    return HealthRead(status="ok")


@router.get("/ready", response_model=HealthRead, responses={503: {"model": HealthRead}})
def ready(request: Request, response: Response) -> HealthRead:
    if not request.app.state.health.ready():
        response.status_code = 503
        return HealthRead(status="unavailable")
    return HealthRead(status="ok")
