import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/mediexplain_db")

def get_db_connection():
    """Establish and return a connection to the PostgreSQL database."""
    try:
        conn = psycopg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        raise e
