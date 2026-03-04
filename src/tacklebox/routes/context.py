from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import SessionContext

router = APIRouter()


@router.get("/context")
async def get_context(
    cwd: str = Query(...),
    scope: str = Query("project"),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(SessionContext)
        .where(SessionContext.cwd == cwd)
        .where(SessionContext.scope == scope)
        .order_by(SessionContext.updated_at.desc())
        .limit(50)
    )
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "key": r.key,
            "value": r.value,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


class ContextUpdate(BaseModel):
    cwd: str
    session_id: str
    key: str
    value: Any
    scope: str = "project"


@router.put("/context")
async def put_context(
    body: ContextUpdate,
    db: AsyncSession = Depends(get_db),
):
    from ..services.audit import resolve_session
    from ..services.context import upsert_project_context

    internal_id = await resolve_session(db, body.session_id, body.cwd)
    await upsert_project_context(db, internal_id, body.cwd, body.key, body.value)
    await db.commit()
    return {"status": "ok"}
