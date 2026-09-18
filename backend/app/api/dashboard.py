"""The workspace at a glance."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import DashboardResponse
from app.services import dashboard as dashboard_service
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(session: Session = Depends(get_session)) -> DashboardResponse:
    """Every number here is counted from the claims in this workspace."""
    with WORKSPACE_LOCK.shared():
        return DashboardResponse.model_validate(dashboard_service.overview(session))
