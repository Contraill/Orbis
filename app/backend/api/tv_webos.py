from fastapi import APIRouter, Request, Response

from tv.webos.renewal import record_checkin, run_due
import asyncio

router = APIRouter(prefix="/api/tv/webos", tags=["tv"])


@router.post("/check-in", status_code=204)
async def check_in(request: Request):
    # No target configuration, credentials or registration status is returned.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 128:
            break
    if len(body) <= 128:
        device_id = body.decode("ascii", errors="ignore").strip()
        if await asyncio.to_thread(record_checkin, device_id):
            asyncio.create_task(asyncio.to_thread(run_due, device_id))
    return Response(status_code=204, headers={"Access-Control-Allow-Origin": "*"})
