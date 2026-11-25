"""Quick test script to verify PostgreSQL connectivity."""

import psycopg

CONNECTION_STRING = "postgresql://postgres:postgres@100.87.23.102:5433/puda"


def main() -> None:
    print(f"Connecting to: {CONNECTION_STRING}")
    try:
        with psycopg.connect(CONNECTION_STRING) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()
                print(f"Connected successfully!")
                print(f"PostgreSQL version: {version[0]}")

                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name;"
                )
                tables = [row[0] for row in cur.fetchall()]
                if tables:
                    print(f"Tables in 'public' schema: {', '.join(tables)}")
                else:
                    print("No tables found in 'public' schema.")
    except psycopg.OperationalError as e:
        print(f"Connection failed: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
