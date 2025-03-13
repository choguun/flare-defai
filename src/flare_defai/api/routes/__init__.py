from fastapi import APIRouter

api_router = APIRouter()

# Import routes after creating api_router to avoid circular imports
from flare_defai.api.routes import chat  # noqa: E402
api_router.include_router(chat.router)

# Import health routes if the module exists
try:
    from flare_defai.api.routes import health  # noqa: E402
    api_router.include_router(health.router)
except ImportError:
    pass

# Import transaction routes if the module exists
try:
    from flare_defai.api.routes import transaction  # noqa: E402
    api_router.include_router(transaction.router)
except ImportError:
    pass
