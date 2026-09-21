from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.profiles import router as profiles_router

app = FastAPI(title="Media App API", version="0.1.0")

app.include_router(profiles_router)

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
