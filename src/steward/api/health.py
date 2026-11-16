from fastapi import APIRouter

from steward import __version__

router = APIRouter()


@router.get("/api/health")
def health():
    return {"ok": True, "version": __version__}
