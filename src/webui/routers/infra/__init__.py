from __future__ import annotations

from fastapi import APIRouter

from .vllm import router as _vllm_router
from .sandbox import router as _sandbox_router
from .services import router as _services_router

router = APIRouter()
router.include_router(_vllm_router)
router.include_router(_sandbox_router)
router.include_router(_services_router)
