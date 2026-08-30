import asyncio
import sys

from sqlalchemy import text
from src.atlasrag.platform.database.engine import get_engine 

REQUIRED_EXTENSIONS = ["vector", "btree_gist"]
engine = get_engine()

async def main() -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text("SELECT extname, extversion FROM pg_extension ORDER BY extname")
        )
        installed = {row.extname: row.extversion for row in result}

    print("Installed extensions:")
    for name, version in installed.items():
        print(f"  {name} ({version})")

    missing = [ext for ext in REQUIRED_EXTENSIONS if ext not in installed]

    await engine.dispose()

    if missing:
        print(f"\nMissing required extensions: {', '.join(missing)}")
        sys.exit(1)

    print("\nAll required extensions are present.")


if __name__ == "__main__":
    asyncio.run(main())
