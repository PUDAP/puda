"""FastAPI dependencies and shared utilities."""
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from the backend directory
# __file__ is at: apps/backend/app/dependencies.py
# .parent = apps/backend/app/
# .parent.parent = apps/backend/
_backend_root = Path(__file__).parent.parent
_env_file = _backend_root / ".env"
# Try loading from backend root first, then fallback to current directory
if _env_file.exists():
    load_dotenv(_env_file)
else:
    # Fallback: try loading from current directory (useful for different execution contexts)
    load_dotenv()