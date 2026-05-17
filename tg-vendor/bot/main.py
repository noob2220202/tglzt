import asyncio
import logging

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
import redis.asyncio as aioredis

from bot.handlers import admin, balance, catalog, orders, purchase, start
from core.cache import init_redis, close_redis
from core.config import settings
from core.db import close_pool, init_pool

logger = structlog.get_logger(__name__)


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def on_startup(bot: Bot) -> None:
    await init_pool()
    await init_redis()
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="시작 / 가입"),
            BotCommand(command="orders", description="내 주문 목록"),
            BotCommand(command="resend", description="인증번호 재발급 /resend <주문번호>"),
            BotCommand(command="cancel", description="현재 작업 취소"),
        ]
    )
    logger.info("bot_started")


async def on_shutdown(bot: Bot) -> None:
    await close_redis()
    await close_pool()
    logger.info("bot_stopped")


async def main() -> None:
    _configure_logging()

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    storage = RedisStorage(redis=redis_client)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=storage)

    # Admin router first — its filter takes priority
    dp.include_router(admin.router)
    dp.include_router(start.router)
    dp.include_router(balance.router)
    dp.include_router(catalog.router)
    dp.include_router(purchase.router)
    dp.include_router(orders.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logger.info("starting_polling")
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types(),
    )


if __name__ == "__main__":
    asyncio.run(main())
