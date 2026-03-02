from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.app.lifespan import lifespan
from src.api.v1.users.router import router as users_router
from src.api.v1.prices.router import router as prices_router
from src.api.v1.parse.router import router as sync_now_parser
from src.api.v1.deals.router import router as deals_router
from src.api.v1.webhooks.router import router as webhooks_router
from src.api.v1.webhooks.router import _handle_bitrix_webhook
from src.api.v1.telegram.router import router as telegram_router
from src.api.v1.offers.router import router as offer_router


from src.core.exceptions import *

app = FastAPI(
    title="My FastAPI App",
    description="My FastAPI App",
    version="0.0.1",
    lifespan=lifespan,
)

# ── CORS (для Telegram Mini App / фронта) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # при необходимости можно сузить до конкретных доменов
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router)
app.include_router(prices_router)
app.include_router(sync_now_parser)
app.include_router(deals_router)
app.include_router(webhooks_router)
app.include_router(telegram_router)
app.include_router(offer_router)

@app.get("/health")
async def check_health():
    return { "status": "ok" }


# ── Catch-all для Bitrix24 вебхуков (шлёт на /webhook/bitrix/deals/ и /) ──

@app.post("/webhook/bitrix/deals/")
@app.post("/webhook/bitrix/deals")
async def bitrix_webhook_legacy(request: Request):
    """Bitrix24 настроен на этот URL — перенаправляем в общий обработчик."""
    return await _handle_bitrix_webhook(request)


@app.post("/")
async def root_webhook(request: Request):
    """Bitrix24 иногда шлёт на корневой URL."""
    return await _handle_bitrix_webhook(request)

@app.exception_handler(UserError)
async def user_exception_handler(request: Request, exc: UserError):
    status_code = 400 
    
    if isinstance(exc, UserAlreadyExistsError):
        status_code = 409  
    elif isinstance(exc, UserDoesNotExistError):
        status_code = 404  
    elif isinstance(exc, UserCannotBeDeletedError):
        status_code = 409
    elif isinstance(exc, UserUpdateError):
        status_code = 409  
    elif isinstance(exc, UserCreateError):
        status_code = 409
    elif isinstance(exc, UserIsNotValidError):
        status_code = 403

    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "error_type": exc.__class__.__name__}
    )


@app.exception_handler(PriceError)
async def price_exception_handler(request: Request, exc: PriceError):
    status_code = 400
    if isinstance(exc, PriceDoesNotExists):
        status_code = 404

    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.message, "error_type": exc.__class__.__name__}
    )