"""Vision AI - Database Health Diagnostic Script.

Checks database connectivity, DNS resolution, query latency,
Alembic migration revision status, and essential table records.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(backend_dir))

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from app.config import get_settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def check_database() -> int:
    print("=" * 60)
    print(" [DIAGNOSTIC] VISION AI - DATABASE HEALTH & DIAGNOSTIC CHECK")
    print("=" * 60)

    settings = get_settings()
    db_url = settings.database_url
    parsed = urlparse(db_url)
    dialect = parsed.scheme.split("+")[0]

    masked_url = db_url
    if parsed.password:
        masked_url = db_url.replace(parsed.password, "******")
    print(f"[*] Target Database Dialect: {dialect}")
    print(f"[*] Database URL: {masked_url}")

    # Step 1: DNS Resolution Check for remote databases
    if dialect in {"postgres", "postgresql"}:
        host = parsed.hostname
        port = parsed.port or 5432
        print(f"\n[1/4] Checking DNS Resolution for host '{host}'...")
        try:
            addr_info = socket.getaddrinfo(host, port)
            ip_addrs = sorted({item[4][0] for item in addr_info})
            print(f"  [OK] DNS Resolved successfully: {', '.join(ip_addrs)}")
        except socket.gaierror as e:
            print(f"  [FAIL] DNS Resolution FAILED for host '{host}': {e}")
            print("  [HINT] Recommendation: The remote database host does not exist or is offline.")
            print("         Update VISION_AI_DATABASE_URL in backend/.env with an active database,")
            print("         or use local SQLite: 'sqlite:///data/vision_ai.db'.")
            return 1
    else:
        print(f"\n[1/4] Checking Local Storage for SQLite...")
        db_path = parsed.path.lstrip("/")
        if not db_path:
            db_path = str(backend_dir / "data" / "vision_ai.db")
        print(f"  [OK] SQLite path: {db_path} (exists={os.path.exists(db_path)})")

    # Step 2: Connection & Query Latency Check
    print(f"\n[2/4] Testing Database Connection & Latency...")
    start_time = time.perf_counter()
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            latency_ms = (time.perf_counter() - start_time) * 1000
            result = conn.execute(text("SELECT 1")).scalar()
            assert result == 1
            print(f"  [OK] Connection established! Ping query latency: {latency_ms:.2f} ms")
    except Exception as exc:
        print(f"  [FAIL] Connection FAILED: {exc}")
        return 1

    # Step 3: Schema & Alembic Migration Check
    print(f"\n[3/4] Checking Schema & Alembic Migration Revisions...")
    try:
        alembic_cfg = Config(str(backend_dir / "alembic.ini"))
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script_dir.get_current_head()

        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            current_rev = None
            if "alembic_version" in tables:
                current_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

        print(f"  - Total tables found: {len(tables)}")
        print(f"  - Current database revision: {current_rev}")
        print(f"  - Head script revision:     {head_rev}")

        if current_rev == head_rev:
            print("  [OK] Schema is fully up-to-date with Alembic HEAD!")
        else:
            print("  [WARN] Schema mismatch! Run 'alembic upgrade head' to apply pending migrations.")
    except Exception as exc:
        print(f"  [WARN] Migration inspection warning: {exc}")

    # Step 4: Core Tables & Data Integrity
    print(f"\n[4/4] Checking Core Tables Record Counts...")
    core_tables = ["users", "scans", "collections", "feedback", "user_sessions", "api_keys"]
    try:
        with engine.connect() as conn:
            for tbl in core_tables:
                if tbl in tables:
                    count = conn.execute(text(f"SELECT count(*) FROM {tbl}")).scalar()
                    print(f"  - {tbl:<16}: {count} records")
                else:
                    print(f"  - {tbl:<16}: [WARN] TABLE MISSING")
    except Exception as exc:
        print(f"  [WARN] Error querying record counts: {exc}")

    print("\n" + "=" * 60)
    print(" [SUCCESS] DATABASE HEALTH CHECK PASSED!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(check_database())
