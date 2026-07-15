import asyncio
from app.db.session import engine
from app.models.models import Base

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("DB tables created/verified")

if __name__ == "__main__":
    asyncio.run(main())
