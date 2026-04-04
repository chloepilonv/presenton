from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlmodel import SQLModel

from models.sql.async_presentation_generation_status import (
    AsyncPresentationGenerationTaskModel,
)
from models.sql.image_asset import ImageAsset
from models.sql.key_value import KeyValueSqlModel
from models.sql.ollama_pull_status import OllamaPullStatus
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sql.presentation_layout_code import PresentationLayoutCodeModel
from models.sql.template import TemplateModel
from models.sql.webhook_subscription import WebhookSubscription
from utils.db_utils import get_database_url_and_connect_args
from utils.get_env import get_migrate_database_on_startup_env


database_url, connect_args = get_database_url_and_connect_args()

sql_engine: AsyncEngine = create_async_engine(database_url, connect_args=connect_args)
async_session_maker = async_sessionmaker(sql_engine, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


# Create Database and Tables
async def create_db_and_tables():
    should_run_alembic = get_migrate_database_on_startup_env() in ["true", "True"]
    if not should_run_alembic:
        async with sql_engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: SQLModel.metadata.create_all(
                    sync_conn,
                    tables=[
                        PresentationModel.__table__,
                        SlideModel.__table__,
                        KeyValueSqlModel.__table__,
                        ImageAsset.__table__,
                        OllamaPullStatus.__table__,
                        PresentationLayoutCodeModel.__table__,
                        TemplateModel.__table__,
                        WebhookSubscription.__table__,
                        AsyncPresentationGenerationTaskModel.__table__,
                    ],
                )
            )
