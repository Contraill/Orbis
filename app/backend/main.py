from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.profiles import router as profiles_router
from api.catalog import router as catalog_router
from api.admin_providers import router as admin_providers_router
from api.provider_editor import router as provider_editor_router

app = FastAPI(title="Media App API", version="0.1.0")

app.include_router(profiles_router)
app.include_router(catalog_router)
app.include_router(admin_providers_router)
app.include_router(provider_editor_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
