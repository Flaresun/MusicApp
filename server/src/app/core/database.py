import os
import logging
from pathlib import Path
from typing import Optional,Any, Sequence
from psycopg_pool import AsyncConnectionPool
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.DEBUG)

# Retrieve database URL from environment or default to local docker-compose settings
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:supersecretpassword@db:5432/monolith_dev"
)

# Global pool instance
pool: Optional[AsyncConnectionPool] = None


async def get_db_pool() -> AsyncConnectionPool:
    """Returns the active global database connection pool."""
    if pool is None:
        raise RuntimeError("Database pool has not been initialized.")
    return pool

async def execute_query(sql: str, params: Sequence[Any] = ()) -> Any:
    """
    Executes a parameterized SQL query against the connection pool.
    
    :param sql: The SQL query string (e.g., "SELECT * FROM users WHERE id = %s")
    :param params: A tuple or list of parameters to safely inject into the query
    :return: List of dictionaries for SELECT / RETURNING queries, or rowcount for write operations.
    """
    active_pool = await get_db_pool()
    
    try:
        # pool.connection() automatically manages transactions (commits on exit, rolls back on error)
        async with active_pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, params)
                
                # If the query returns rows (e.g., SELECT, INSERT ... RETURNING)
                if cur.description is not None:
                    return await cur.fetchall()
                
                # For non-returning write queries (UPDATE, DELETE, INSERT)
                return cur.rowcount

    except psycopg.Error as e:
        logger.error(f"Database query error: {e} | Query: {sql} | Params: {params}")
        raise e
    except Exception as e:
        logger.error(f"Unexpected error executing query: {e}")
        raise e

async def init_db():
    """Initializes the connection pool and runs schema.sql if tables do not exist."""
    global pool
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        open=False,
        min_size=1,
        max_size=10,
    )
    await pool.open()
    logger.info("Database connection pool established.")

    # Check if the schema has already been applied
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'users'
                );
                """
            )
            result = await cur.fetchone()
            schema_exists = result[0] if result else False

            if not schema_exists:
                logger.info("Initializing database schema from schema.sql...")
                schema_path = Path(__file__).parent / "schema.sql"
                
                if not schema_path.exists():
                    logger.error(f"schema.sql not found at {schema_path}")
                    raise FileNotFoundError(f"schema.sql missing at {schema_path}")

                schema_sql = schema_path.read_text(encoding="utf-8")
                await cur.execute(schema_sql)
                await conn.commit()
                logger.info("Database schema initialized successfully.")
            else:
                logger.info("Database schema already exists. Skipping schema execution.")


async def close_db():
    """Closes the connection pool on application shutdown."""
    global pool
    if pool:
        await pool.close()
        logger.info("Database connection pool closed.")


async def check_db_health() -> bool:
    """Queries the database to verify active connectivity."""
    if pool is None:
        return False
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False