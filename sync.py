import os
import requests
import psycopg2
import pyodbc
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Airtable setup
API_KEY = os.getenv('AIRTABLE_API_KEY')
BASE_ID = os.getenv('AIRTABLE_BASE_ID')
TABLE_NAME = os.getenv('AIRTABLE_TABLE_NAME')
AIRTABLE_URL = f'https://api.airtable.com/v0/{BASE_ID}/{TABLE_NAME}'

headers = {
    'Authorization': f'Bearer {API_KEY}',
}

# Database configuration
DB_TYPE = os.getenv('DB_TYPE', 'postgres').lower()

# Establish database connection
conn = None
cur = None

if DB_TYPE == 'postgres':
    # PostgreSQL setup
    conn = psycopg2.connect(
        dbname=os.getenv('PG_DBNAME'),
        user=os.getenv('PG_USER'),
        password=os.getenv('PG_PASSWORD'),
        host=os.getenv('PG_HOST'),
        port=os.getenv('PG_PORT')
    )

    cur = conn.cursor()

    # Create a basic table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS airtable_data (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT
        )
    """)
elif DB_TYPE == 'sqlserver':
    # SQL Server setup
    server = os.getenv('SQLSERVER_HOST', 'localhost')
    database = os.getenv('SQLSERVER_DB', 'airtable_mirror')

    # Using Windows Authentication (Trusted Connection)
    conn_string = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"

    conn = pyodbc.connect(conn_string)
    cur = conn.cursor()

    # Check if table exists, if not create it
    cur.execute("""
        IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'airtable_data')
        BEGIN
            CREATE TABLE airtable_data (
                id NVARCHAR(100) PRIMARY KEY,
                name NVARCHAR(MAX),
                email NVARCHAR(MAX)
            )
        END
    """)
    conn.commit()
else:
    raise ValueError(f"Unsupported database type: {DB_TYPE}")

# Fetch records
r = requests.get(AIRTABLE_URL, headers=headers)
records = r.json()['records']

for rec in records:
    data = rec['fields']
    if DB_TYPE == 'postgres':
        # PostgreSQL insert with conflict handling
        cur.execute(
            "INSERT INTO airtable_data (id, name, email) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (rec['id'], data.get('Name', ''), data.get('Email', ''))
        )
    else:
        # SQL Server insert with existence check
        cur.execute("SELECT COUNT(*) FROM airtable_data WHERE id = ?", (rec['id'],))
        if cur.fetchone()[0] == 0:
            # Insert if not exists
            cur.execute(
                "INSERT INTO airtable_data (id, name, email) VALUES (?, ?, ?)",
                (rec['id'], data.get('Name', ''), data.get('Email', ''))
            )

conn.commit()
cur.close()
conn.close()
print(f"✅ Data pulled from Airtable and loaded into {DB_TYPE.capitalize()}.")
