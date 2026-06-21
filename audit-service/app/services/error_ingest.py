"""Error ingest service for HTTP API."""
from __future__ import annotations

import logging

from app.core.database import AsyncSessionLocal
from app.services.audit_ingest import ingest_error

logger = logging.getLogger("audit_service.error_ingest")


class ErrorIngestService:
    async def ingest(self, payload: dict) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await ingest_error(db, payload)
                await db.commit()
        except Exception as e:
            logger.error("failed to ingest error", exc_info=True, extra={"error": str(e)})
            raise
