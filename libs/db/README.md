# puda-db

PostgreSQL database client library for the PUDA platform.

## Usage

```python
from puda_db import DatabaseClient

# Connect to database
with DatabaseClient(
    host="localhost",
    port=5432,
    database="puda",
    user="puda",
    password="password"
) as db:
    # Execute queries
    results = db.execute("SELECT * FROM machines WHERE id = %(id)s", {"id": 1})
    
    # Insert/update data
    db.execute_update(
        "INSERT INTO executions (machine_id, status) VALUES (%(machine_id)s, %(status)s)",
        {"machine_id": 1, "status": "running"}
    )
```

## Installation

This library is part of the PUDA workspace and can be used by adding it to your service's `pyproject.toml`:

```toml
dependencies = [
    "puda-db",
]

[tool.uv.sources]
puda-db = {workspace = true}
```

