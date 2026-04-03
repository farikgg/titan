from fastapi import FastAPI, Request, APIRouter
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.app.lifespan import lifespan
from src.api.v1.users.router import router as users_router
from src.api.v1.prices.router import router as prices_router
from src.api.v1.parse.router import router as sync_now_parser
from src.api.v1.deals.router import router as deals_router
from src.api.v1.webhooks.router import router as webhooks_router
from src.api.v1.webhooks.router import _handle_bitrix_webhook
from src.api.v1.telegram.router import router as telegram_router
from src.api.v1.offers.router import router as offer_router
from src.api.v1.analogs.router import router as analogs_router


from src.core.exceptions import *

ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://167.99.243.146:3002",
}


def _cors_headers(origin: str | None) -> dict[str, str]:
    if origin and (origin in ALLOWED_ORIGINS or "trycloudflare.com" in origin):
        allow_origin = origin
    else:
        allow_origin = "http://167.99.243.146:3002"
    return {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Init-Data, token, Authorization, ngrok-skip-browser-warning",
        "Access-Control-Max-Age": "86400",
    }


class AddCORSHeadersMiddleware(BaseHTTPMiddleware):
    """Добавляет CORS-заголовки к каждому ответу. OPTIONS обрабатывает маршрут ниже."""
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        origin = request.headers.get("origin")
        for k, v in _cors_headers(origin).items():
            response.headers[k] = v
        return response


app = FastAPI(
    title="My FastAPI App",
    description="My FastAPI App",
    version="0.0.1",
    lifespan=lifespan,
)

# Сначала свой CORS (к каждому ответу), потом CORSMiddleware
app.add_middleware(AddCORSHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_origin_regex=r"https://.*\.trycloudflare\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Базовые роуты (без префикса) — для совместимости и прямого доступа по IP/порт 8000
app.include_router(users_router)
app.include_router(prices_router)
app.include_router(sync_now_parser)
app.include_router(deals_router)
app.include_router(webhooks_router)
app.include_router(telegram_router)
app.include_router(offer_router)
app.include_router(analogs_router)

# Дубликат роутов под префиксом /api/v1 — для фронта и домена aliks.fun
api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(users_router)
api_v1.include_router(prices_router)
api_v1.include_router(sync_now_parser)
api_v1.include_router(deals_router)
api_v1.include_router(webhooks_router)
api_v1.include_router(telegram_router)
api_v1.include_router(offer_router)
api_v1.include_router(analogs_router)
app.include_router(api_v1)


@app.options("/{rest:path}")
async def cors_preflight(rest: str, request: Request):
    """Явный ответ на preflight (OPTIONS), чтобы CORS точно работал за ngrok."""
    origin = request.headers.get("origin") or ""
    allow = (
        origin
        if (origin in ALLOWED_ORIGINS or "trycloudflare.com" in origin)
        else "http://167.99.243.146:3002"
    )
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": allow,
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, X-Telegram-Init-Data, token, Authorization, ngrok-skip-browser-warning",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "86400",
        },
    )


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
