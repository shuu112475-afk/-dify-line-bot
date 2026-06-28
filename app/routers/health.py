from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return JSONResponse({"ok": True})


@router.get("/readyz")
async def readyz():
    return JSONResponse({"ok": True})
