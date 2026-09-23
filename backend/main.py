from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from atomic_step_agent import TaskPlanAgent
from evomap_client import EvoMapClient, EvoMapError, OAuthAttempt
from llm_client import OpenAICompatibleClient
from mindloop import MindLoopService

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


evomap = EvoMapClient(
    base_url=os.getenv("EVOMAP_BASE_URL", "https://evomap.ai"),
    client_id=os.getenv("EVOMAP_CLIENT_ID", ""),
    client_secret=os.getenv("EVOMAP_CLIENT_SECRET", ""),
    redirect_uri=os.getenv("EVOMAP_REDIRECT_URI", "http://localhost:8000/oauth/callback"),
    scopes=os.getenv(
        "EVOMAP_SCOPES",
        "recipe:read gene:read reuse:query recipe:write recipe:publish",
    ),
    token=os.getenv("EVOMAP_TOKEN"),
)

app = FastAPI(title="MindLoop EvoMap Bridge", version="0.1.0")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
oauth_attempts: dict[str, OAuthAttempt] = {}
mindloop = MindLoopService(
    Path(os.getenv("MINDLOOP_DB_PATH", "mindloop.db")),
    os.getenv("EVOMAP_RECIPE_ID") or None,
)
llm_client = OpenAICompatibleClient(
    base_url=os.getenv("AI_BASE_URL", "https://api.evomap.ai/v1"),
    api_key=os.getenv("AI_API_KEY", ""),
    model=os.getenv("AI_MODEL", "evomap-deepseek-v4-flash"),
    timeout_seconds=float(os.getenv("AI_TIMEOUT_SECONDS", "40")),
    max_retries=int(os.getenv("AI_MAX_RETRIES", "1")),
)
plan_agent = TaskPlanAgent(
    llm_client,
    fallback_enabled=env_bool("AI_FALLBACK_ENABLED", True),
)


class RecipeStep(BaseModel):
    asset_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class RecipeInput(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=2000)
    steps: list[RecipeStep] = Field(min_length=1)


class MindLoopStartInput(BaseModel):
    task: str = Field(min_length=2, max_length=1000)
    friction: str = Field(default="unclear_first_step", max_length=100)


class MindLoopFeedbackInput(BaseModel):
    session_id: str = Field(pattern=r"^session_[a-f0-9]{12}$")
    result: str = Field(pattern=r"^(done|stuck)$")


@app.get("/", include_in_schema=False)
async def product_demo():
    return FileResponse(static_dir / "index.html")


@app.exception_handler(EvoMapError)
async def evomap_error_handler(_: Request, exc: EvoMapError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "evomap_error", "detail": exc.detail},
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "evomap": {
            "configured": bool(evomap.client_id and evomap.client_secret),
            "authenticated": bool(evomap.token),
            "test_mode": evomap.is_test_mode,
        },
        "ai": {
            "configured": llm_client.configured,
            "model": llm_client.model,
            "timeout_seconds": llm_client.timeout_seconds,
            "max_retries": llm_client.max_retries,
            "fallback_enabled": plan_agent.fallback_enabled,
        },
    }


@app.get("/oauth/start")
async def oauth_start():
    if not evomap.client_id or not evomap.client_secret:
        raise HTTPException(503, "Set EVOMAP_CLIENT_ID and EVOMAP_CLIENT_SECRET first")
    url, attempt = evomap.build_authorization_url()
    oauth_attempts[attempt.state] = attempt
    return RedirectResponse(url)


@app.get("/oauth/callback")
async def oauth_callback(code: str, state: str) -> dict[str, Any]:
    attempt = oauth_attempts.pop(state, None)
    if not attempt:
        raise HTTPException(400, "Invalid or expired OAuth state")
    token_data = await evomap.exchange_code(code=code, verifier=attempt.verifier)
    return {
        "connected": True,
        "scope": token_data.get("scope"),
        "expires_in": token_data.get("expires_in"),
        "test_mode": evomap.is_test_mode,
        "next": "/docs",
    }


@app.get("/api/evomap/recipes/search")
async def search_recipes(
    q: str = Query(min_length=2, max_length=240),
    limit: int = Query(default=5, ge=1, le=20),
):
    return await evomap.search_recipes(q, limit)


@app.get("/api/evomap/genes")
async def list_genes(
    gene_type: str | None = Query(default=None, alias="type", max_length=100),
    limit: int = Query(default=5, ge=1, le=20),
):
    return await evomap.list_genes(gene_type=gene_type, limit=limit)


@app.get("/api/evomap/reuse")
async def reuse_graph(
    recipe_id: str | None = None,
    asset_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
):
    try:
        return await evomap.query_reuse(
            recipe_id=recipe_id,
            asset_id=asset_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/evomap/recipes/draft")
async def create_recipe_draft(recipe: RecipeInput):
    return await evomap.create_recipe_draft(
        recipe.model_dump(),
        idempotency_key=str(uuid4()),
    )


@app.post("/api/evomap/recipes/publish-test")
async def publish_recipe_test(recipe: RecipeInput):
    if not env_bool("EVOMAP_ALLOW_TEST_PUBLISH"):
        raise HTTPException(403, "Set EVOMAP_ALLOW_TEST_PUBLISH=true to enable")
    try:
        return await evomap.publish_recipe_test_mode(
            recipe.model_dump(),
            idempotency_key=str(uuid4()),
        )
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc


@app.post("/api/mindloop/start")
async def mindloop_start(payload: MindLoopStartInput):
    """Create a complete ordered plan and present only its first step."""
    task_type = mindloop.classify_task(payload.task)
    generated = await plan_agent.generate_plan(
        task=payload.task,
        task_type=task_type,
        friction=payload.friction,
        recipe_id=mindloop.recipe_id,
        memory_profile=mindloop.memory_profile(task_type),
    )
    return mindloop.start(
        task=payload.task,
        friction=payload.friction,
        generated_plan=generated.plan.model_dump() if generated.plan else None,
        step_source=generated.source,
    )


async def refine_stuck_plan(
    session_id: str, expected_plan_version: int, expected_step_index: int,
    context: dict[str, Any],
) -> None:
    generated = await plan_agent.replan(
        task=context["task"], task_type=context["task_type"],
        completed_steps=context["completed_steps"], current_step=context["current_step"],
        remaining_steps=context["remaining_steps"], recipe_id=context["recipe_id"],
        memory_profile=mindloop.memory_profile(context["task_type"]),
    )
    if generated.revised_steps:
        mindloop.apply_background_replan(
            session_id=session_id, expected_plan_version=expected_plan_version,
            expected_step_index=expected_step_index,
            revised_steps=[step.model_dump() for step in generated.revised_steps],
        )


@app.post("/api/mindloop/feedback")
async def mindloop_feedback(payload: MindLoopFeedbackInput, background_tasks: BackgroundTasks):
    """Advance after Done; shrink immediately and refine in background after Stuck."""
    try:
        if payload.result == "stuck":
            context = mindloop.context(payload.session_id)
            response = mindloop.feedback(
                session_id=payload.session_id, result="stuck",
                revised_steps=None, step_source="local_adjustment",
            )
            if response.get("hint"):
                return response
            background_tasks.add_task(
                refine_stuck_plan, payload.session_id, response["plan_version"],
                response["current_step_index"], context,
            )
            return response
        return mindloop.feedback(session_id=payload.session_id, result="done")
    except KeyError as exc:
        raise HTTPException(404, "Session not found or server was restarted") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/mindloop/session/{session_id}")
async def mindloop_session(session_id: str):
    """Return the latest step, including an optional background AI refinement."""
    try:
        return mindloop.session_response(session_id)
    except KeyError as exc:
        raise HTTPException(404, "Session not found or server was restarted") from exc


@app.get("/api/mindloop/metrics")
async def mindloop_metrics():
    return mindloop.metrics()


@app.get("/api/mindloop/events")
async def mindloop_events(limit: int = Query(default=20, ge=1, le=100)):
    return {"events": mindloop.events(limit)}


@app.get("/api/mindloop/memory")
async def mindloop_memory(task_type: str = Query(default="general", max_length=50)):
    """Inspect the anonymous personalization evidence used by the AI."""
    return mindloop.memory_profile(task_type)
