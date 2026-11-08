"""FastAPI app. Run with:  uvicorn app.main:app --reload"""
from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .errors import ApiError, ParseError
from .limits import BodyLimitMiddleware, RateLimiter, RateLimitMiddleware
from .presets import BUILTIN_PRESETS, DEFAULT_PRESET, PresetDef
from .rules import RULES
from .schemas import (
    AnalyzeRequest, AnalyzeResponse, ErrorResponse, RuleInfo, SimplifyRequest, SimplifyResponse, SynthesizeRequest,
)
from .service import analyze, resolve_preset, simplify, synthesize


async def _keep_alive(url: str) -> None:
    """Pings our own public URL so a free host does not spin the service down after 15 idle minutes."""
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await asyncio.sleep(600)
            try:
                await client.get(f"{url}/api/health")
            except Exception:
                pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    url = os.environ.get("RENDER_EXTERNAL_URL")      # set automatically by Render; absent locally
    task = asyncio.create_task(_keep_alive(url)) if url else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    title="Boolean Lab API",
    version="0.1.0",
    description="Parses boolean expressions and returns truth table, forms, K-map and circuit data.",
    lifespan=lifespan,
)

# Middleware order: the LAST one added is the OUTERMOST, so a request meets them in this order:
# CORS -> gzip -> rate limit -> body size limit -> the app. CORS is outermost so that even a 429 or 413
# carries the CORS headers; otherwise the browser would hide the message behind a generic network error.
app.add_middleware(BodyLimitMiddleware, max_bytes=config.MAX_BODY_BYTES)
limiter = RateLimiter(config.RATE_LIMITS)      # module level so tests can reset its counters
app.add_middleware(RateLimitMiddleware, limiter=limiter, trust_proxy=config.TRUST_PROXY,
                   client_ip_header=config.CLIENT_IP_HEADER)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Frontend dev servers that may call this API. Override with BOOLEAN_LAB_CORS="https://a.com,https://b.com"
_origins = os.environ.get("BOOLEAN_LAB_CORS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# -- one error shape for everything: {"error": {"code", "message", "position"?}} ---------------
@app.exception_handler(ParseError)
async def _parse_error(_: Request, exc: ParseError) -> JSONResponse:
    body = {"error": {"code": "parse_error", "message": exc.message, "position": exc.position + 1}}
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    text = str(first.get("msg", "invalid value")).removeprefix("Value error, ")
    message = f"{where}: {text}" if where else text
    return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": message}})


# -- routes -----------------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/presets", response_model=list[PresetDef])
def list_presets() -> list[PresetDef]:
    """Built-in presets with every operator, its symbols, precedence and truth table."""
    ordered = [DEFAULT_PRESET] + [name for name in BUILTIN_PRESETS if name != DEFAULT_PRESET]
    return [BUILTIN_PRESETS[name] for name in ordered]


@app.post("/api/presets/validate", response_model=PresetDef)
def validate_preset(preset: PresetDef) -> PresetDef:
    """Returns the preset normalised (symbols trimmed, words lowercased) or a 422 explaining the problem."""
    return preset


@app.post(
    "/api/analyze",
    response_model=AnalyzeResponse,
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def analyze_expression(request: AnalyzeRequest) -> dict:
    preset = resolve_preset(request.preset, request.custom_preset)
    return analyze(request.expression, preset, request.circuit_mode)


@app.post(
    "/api/synthesize",
    response_model=AnalyzeResponse,
    responses={422: {"model": ErrorResponse}},
)
def synthesize_function(request: SynthesizeRequest) -> dict:
    """Table to function: same response shape as /api/analyze, so the same screens can show it."""
    return synthesize(request.outputs, request.variables or [], request.function_form, request.circuit_mode)


# How many simplifications may run at the same moment. They are CPU work, so a crowd of simultaneous
# requests would slow every other user down. A request that finds no free slot is told to retry (503).
_simplify_slots = threading.BoundedSemaphore(config.SIMPLIFY_MAX_PARALLEL)


@app.get("/api/simplify/rules", response_model=list[RuleInfo])
def simplify_rules() -> list[dict]:
    """The rule sheet (postulates P1-P5, theorems T1-T6 and the three helper rules) the simplifier names its steps with."""
    return list(RULES.values())


@app.post(
    "/api/simplify",
    response_model=SimplifyResponse,
    responses={413: {"model": ErrorResponse}, 422: {"model": ErrorResponse},
               429: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def simplify_expression(request: SimplifyRequest) -> dict:
    """Simplifies step by step; every step is named after a rule of the course sheet.
    Heavy, so it is rate limited more strictly than the other endpoints and the frontend only calls it on a click."""
    preset = resolve_preset(request.preset, request.custom_preset)
    if not _simplify_slots.acquire(blocking=False):
        raise ApiError("busy", "The server is simplifying other expressions right now. Try again in a few seconds.", 503)
    try:
        return simplify(request.expression, preset)
    finally:
        _simplify_slots.release()


# Optional: serve the built React app from the same server (BOOLEAN_LAB_STATIC=../frontend/dist).
_static = os.environ.get("BOOLEAN_LAB_STATIC")
if _static and Path(_static).is_dir():
    app.mount("/", StaticFiles(directory=_static, html=True), name="frontend")
