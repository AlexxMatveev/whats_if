from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.routers.analysis import router as analysis_router
from app.routers.diagram import router as diagram_router
from app.routers.architecture import router as architecture_router

app = FastAPI(
    title="Whats If — Анализ сценариев",
    description="Сервис для анализа сценариев «что если» для распределённых систем.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis_router)
app.include_router(diagram_router)
app.include_router(architecture_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")
