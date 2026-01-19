from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse

from src.app.lifespan import lifespan
from src.api.v1.users.router import router as users_router
from src.api.v1.prices.router import router as prices_router

from src.core.exceptions import *

app = FastAPI(
    title="My FastAPI App",
    description="My FastAPI App",
    version="0.0.1",
    lifespan=lifespan,
)
app.include_router(users_router)
app.include_router(prices_router)

@app.get("/health")
async def check_health():
    return { "status": "ok" }

@app.exception_handler(UserError)
async def user_exception_handler(request: Request, exc: UserError):
    status_code = 400 
    
    if isinstance(exc, UserAlreadyExistsError):
        status_code = 409  
    elif isinstance(exc, UserDoesNotExistError):
        status_code = 404  
    elif isinstance(exc, UserCannotBeDeletedError):
        status_code = 403  

    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "error_type": exc.__class__.__name__}
    )