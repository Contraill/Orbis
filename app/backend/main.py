from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from api.profiles import router as profiles_router
from api.catalog import router as catalog_router
from api.admin_providers import router as admin_providers_router
from api.provider_editor import router as provider_editor_router
from api.playback import router as playback_router
from api.playback_proxy import router as playback_proxy_router
from api.setup import router as setup_router
from core.auth import require_owner
from api.library import router as library_router
from api.feeds import router as feeds_router
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse

app = FastAPI(title="Orbis API", version="0.1.0")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    if request.url.path.startswith("/api/setup"):
        # Pydantic validation errors can otherwise echo the submitted password.
        return JSONResponse(status_code=422, content={"detail": [
            {key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()
        ]})
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def private_admin_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/setup", "/api/admin")):
        response.headers["Cache-Control"] = "no-store"
    return response

app.include_router(profiles_router)
app.include_router(catalog_router)
app.include_router(setup_router)
app.include_router(library_router)
app.include_router(feeds_router)
app.include_router(admin_providers_router, dependencies=[Depends(require_owner)])
app.include_router(provider_editor_router, dependencies=[Depends(require_owner)])
app.include_router(playback_router)
app.include_router(playback_proxy_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "media-app-backend",
        "version": "0.1.0",
    }
