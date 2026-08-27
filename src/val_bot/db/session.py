from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine


def make_engine(db_path: str) -> AsyncEngine:
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}")


def make_session_factory(engine: AsyncEngine):
    return async_sessionmaker(engine, expire_on_commit=False)
