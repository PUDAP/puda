# PostgreSQL Database Setup

## Quick Start

1. Copy the template: `cp .env.example .env` (if you need custom configuration)

2. Edit `.env` and fill in your database credentials (optional, defaults are provided)

3. Start the database: `docker compose up -d`

4. Connect to the database:
   ```bash
   docker exec -it postgres psql -U postgres -d puda
   ```

## Environment Variables

- `POSTGRES_USER` - Database user (default: `postgres`)
- `POSTGRES_PASSWORD` - Database password (default: `postgres`)
- `POSTGRES_DB` - Database name (default: `puda`)

## Connection String

```
postgresql://postgres:postgres@postgres:5432/puda
```

From host machine:
```
postgresql://postgres:postgres@localhost:5432/puda
```

## Initialization

Place any SQL initialization scripts in `init.sql` - they will be automatically executed on first startup.

## Data Persistence

Database data is persisted in the `postgres_data` Docker volume.

## Backup

Create a backup of the database:

```bash
docker exec -i postgres pg_dump -U postgres puda > backup.sql
```

Or with custom credentials:

```bash
docker exec -i <container_name> pg_dump -U <username> <database_name> > backup.sql
```

