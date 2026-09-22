"""Sequential claim numbers: <series>-<5-digit sequence>, e.g. CLM-2026-00123.

Counted per workspace. Someone arriving at a deployment that keeps visitors apart creates
CLM-2026-00123 as their first claim whoever else has been here — the number says where a claim
sits in that person's work, not how many strangers came before them.
"""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.access.scope import current_owner
from app.config import get_settings
from app.models import ClaimCounter


def format_claim_number(value: int) -> str:
    return f"{get_settings().claim_series}-{value:05d}"


def ensure_counter(session: Session, owner: str | None = None) -> ClaimCounter:
    settings = get_settings()
    owner = current_owner() if owner is None else owner
    counter = session.get(ClaimCounter, (settings.claim_series, owner))
    if counter is None:
        counter = ClaimCounter(
            series=settings.claim_series, owner=owner, next_value=settings.claim_sequence_start
        )
        session.add(counter)
        session.flush()
    return counter


def allocate_claim_number(session: Session) -> str:
    """Reserve the next number with a single atomic UPDATE ... RETURNING in the caller's transaction."""
    owner = current_owner()
    statement = (
        update(ClaimCounter)
        .where(ClaimCounter.series == get_settings().claim_series, ClaimCounter.owner == owner)
        .values(next_value=ClaimCounter.next_value + 1)
        .returning(ClaimCounter.next_value)
        .execution_options(synchronize_session=False)
    )
    incremented = session.execute(statement).scalar_one_or_none()
    if incremented is None:
        ensure_counter(session, owner)
        incremented = session.execute(statement).scalar_one()
    return format_claim_number(incremented - 1)


def peek_next_claim_number(session: Session) -> str:
    settings = get_settings()
    value = session.scalar(
        select(ClaimCounter.next_value).where(
            ClaimCounter.series == settings.claim_series, ClaimCounter.owner == current_owner()
        )
    )
    return format_claim_number(value if value is not None else settings.claim_sequence_start)
