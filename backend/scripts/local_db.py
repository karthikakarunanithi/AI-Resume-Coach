"""Local Postgres 16 + pgvector without Docker, using the binaries bundled with the `pgserver` dev package.

Runs on port 5433 so it doesn't clash with a system Postgres on 5432. Data lives in data/pgdata (gitignored).

Usage (from backend/):
    python -m scripts.local_db start     # first run also creates the database (user coach / password coach)
    python -m scripts.local_db status
    python -m scripts.local_db psql      # interactive SQL shell on the app database
    python -m scripts.local_db stop
"""

import os
import subprocess
import sys
from pathlib import Path

from pgserver._commands import POSTGRES_BIN_PATH

from app.config import ROOT_DIR

PORT = 5433
DATA = ROOT_DIR / "data" / "pgdata"
LOG = ROOT_DIR / "data" / "pgdata.log"
DB_USER = DB_PASSWORD = DB_NAME = "coach"
# 127.0.0.1, not "localhost": on Windows localhost tries IPv6 first and stalls ~2 s on every new connection
URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@127.0.0.1:{PORT}/{DB_NAME}"


def _bin(name: str) -> str:
    return str(POSTGRES_BIN_PATH / f"{name}.exe" if os.name == "nt" else POSTGRES_BIN_PATH / name)


def _run(*args: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=check, text=True, capture_output=True, **kwargs)


def _sql(sql: str, db: str = "postgres", user: str = "postgres") -> str:
    out = _run(_bin("psql"), "-h", "127.0.0.1", "-p", str(PORT), "-U", user, "-d", db, "-tAc", sql)
    return out.stdout.strip()


def ensure_timezone_data() -> None:
    """pgserver's Postgres build ships without a time zone database, so only "GMT" works and clients that send
    their zone on connect (DBeaver, pgAdmin, any JDBC tool) fail with: invalid value for parameter "TimeZone".
    Postgres reads standard TZif files, which the `tzdata` package provides."""
    import shutil

    import tzdata

    target = POSTGRES_BIN_PATH.parent / "share" / "postgresql" / "timezone"
    if (target / "UTC").exists():
        return
    shutil.copytree(Path(tzdata.__file__).parent / "zoneinfo", target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__init__.py", "__pycache__"))
    print(f"Installed time zone data into {target}")


def running() -> bool:
    return _run(_bin("pg_ctl"), "status", "-D", str(DATA), check=False).returncode == 0


def start() -> None:
    ensure_timezone_data()
    first_run = not (DATA / "PG_VERSION").exists()
    if first_run:
        DATA.parent.mkdir(parents=True, exist_ok=True)
        print(f"Creating a new database cluster in {DATA} ...")
        # Local-only server (listens on 127.0.0.1), so trust auth is fine for development
        _run(_bin("initdb"), "-D", str(DATA), "-U", "postgres", "--auth=trust", "-E", "UTF8")
    if running():
        print(f"Already running on port {PORT}.")
    else:
        # No captured output here: the server process would inherit the pipe and the call would never return
        subprocess.run(
            [_bin("pg_ctl"), "start", "-D", str(DATA), "-l", str(LOG), "-w",
             "-o", f"-p {PORT} -c listen_addresses=127.0.0.1"],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"Postgres started on port {PORT}.")
    if first_run or not _sql(f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'"):
        _sql(f"CREATE ROLE {DB_USER} LOGIN PASSWORD '{DB_PASSWORD}'")
        _sql(f"CREATE DATABASE {DB_NAME} OWNER {DB_USER}")
        _sql("CREATE EXTENSION IF NOT EXISTS vector", db=DB_NAME)  # needs superuser, so not left to migrations
        print(f"Created database '{DB_NAME}' (user {DB_USER}) with pgvector.")
    print(f"\nDATABASE_URL={URL}")


def stop() -> None:
    if running():
        _run(_bin("pg_ctl"), "stop", "-D", str(DATA), "-m", "fast")
        print("Postgres stopped.")
    else:
        print("Not running.")


def status() -> None:
    if not running():
        print("Not running. Start it with: python -m scripts.local_db start")
        return
    tables = _sql("SELECT string_agg(tablename, ', ' ORDER BY tablename) FROM pg_tables WHERE schemaname = 'public'",
                  db=DB_NAME, user=DB_USER)
    print(f"Running on port {PORT}.\nDATABASE_URL={URL}\nTables: {tables or '(none yet: run alembic upgrade head)'}")


def psql() -> None:
    sys.exit(subprocess.call([_bin("psql"), "-h", "127.0.0.1", "-p", str(PORT), "-U", DB_USER, "-d", DB_NAME]))


if __name__ == "__main__":
    commands = {"start": start, "stop": stop, "status": status, "psql": psql}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]]()
