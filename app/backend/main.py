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
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.errors import http_error, validation_error, error_response
from core.logging import install as install_logging

install_logging()

from api.watch_together import router as watch_together_router, room_lifespan

app = FastAPI(title="Orbis API", version="1.0.0", lifespan=room_lifespan)
app.add_exception_handler(StarletteHTTPException,http_error)
app.add_exception_handler(RequestValidationError,validation_error)


@app.middleware("http")
async def private_admin_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
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
        "version": "1.0.0",
        "api_version": "v1",
    }


from api.client_sessions import router as client_sessions_router
from api.episodes import router as episodes_router, admin_router as markers_router
from playback.capabilities import ClientCompatibilityError
app.include_router(client_sessions_router)
app.include_router(episodes_router)
app.include_router(markers_router)


@app.exception_handler(ClientCompatibilityError)
async def incompatible_client(request, exc):
    return error_response(409,{"code":str(exc),"message":"No compatible playback source or variant is available for this client"})

app.include_router(watch_together_router)

from api.system import router as system_router
app.include_router(system_router)

from core.openapi import install as install_openapi
install_openapi(app)

@app.exception_handler(Exception)
async def internal_error(request,exc):
    import logging
    logging.getLogger(__name__).error('request_failed type=%s',type(exc).__name__)
    return error_response(500,'Internal server error')
