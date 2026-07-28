from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import datasets, eval, match

app = FastAPI(title="Concord")

app.include_router(datasets.router)
app.include_router(match.router)
app.include_router(eval.router)

# Mounted last: a root mount only serves paths not already matched by a router
# above it, so this doesn't shadow the API routes.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
