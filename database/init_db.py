import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

def init_db():
    conn = psycopg.connect(DATABASE_URL)
    with conn.cursor() as cur:
        # Users table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # Lab documents uploaded by users
        cur.execute('''
            CREATE TABLE IF NOT EXISTS lab_documents (
                id SERIAL PRIMARY KEY,
                user_id INT REFERENCES users(id) ON DELETE CASCADE,
                filename VARCHAR(255) NOT NULL,
                file_path TEXT NOT NULL,
                uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        ''')

        # Extracted lab metrics/values
        cur.execute('''
            CREATE TABLE IF NOT EXISTS lab_metrics (
                id SERIAL PRIMARY KEY,
                document_id INT REFERENCES lab_documents(id) ON DELETE CASCADE,
                test_name VARCHAR(255) NOT NULL,
                test_value VARCHAR(100) NOT NULL,
                unit VARCHAR(50),
                reference_range VARCHAR(100),
                status VARCHAR(50)
            );
        ''')

        # Plain-language explanation reports
        cur.execute('''
            CREATE TABLE IF NOT EXISTS explanation_reports (
                id SERIAL PRIMARY KEY,
                document_id INT REFERENCES lab_documents(id) ON DELETE CASCADE,
                summary TEXT NOT NULL,
                recommendations TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.commit()
        print('Database tables initialized successfully!')
    conn.close()

if __name__ == '__main__':
    init_db()
