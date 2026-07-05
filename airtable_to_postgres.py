import requests
import psycopg2
import logging
from typing import Dict, List, Any
import json
from datetime import datetime
import os
from dotenv import load_dotenv
from pathlib import Path
import time

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('airtable_sync.log'),
        logging.StreamHandler()
    ]
)

# Security: Ensure .env file has proper permissions
env_file = Path('.env')
if env_file.exists():
    env_file.chmod(0o600)  # Only owner can read/write

class AirtableToPostgres:
    def __init__(self):
        self.airtable_token = os.getenv('AIRTABLE_TOKEN')
        if not self.airtable_token:
            raise ValueError("AIRTABLE_TOKEN not found in environment variables")

        self.headers = {'Authorization': f'Bearer {self.airtable_token}'}
        self.conn = None
        self.cur = None
        self.rate_limit_delay = 0.2  # 200ms delay between API calls

    def get_pg_conn_params(self) -> Dict[str, str]:
        """Get PostgreSQL connection parameters from environment variables"""
        return {
            'dbname': os.getenv('POSTGRES_DB'),
            'user': os.getenv('POSTGRES_USER'),
            'password': os.getenv('POSTGRES_PASSWORD'),
            'host': os.getenv('POSTGRES_HOST'),
            'port': os.getenv('POSTGRES_PORT')
        }

    def connect_to_postgres(self):
        """Establish connection to PostgreSQL"""
        try:
            conn_params = self.get_pg_conn_params()
            self.conn = psycopg2.connect(**conn_params)
            self.cur = self.conn.cursor()
            logging.info("Connected to PostgreSQL successfully")
        except Exception as e:
            logging.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    def get_all_workspaces(self) -> List[Dict[str, Any]]:
        """Fetch all workspaces from Airtable"""
        try:
            response = requests.get(
                'https://api.airtable.com/v0/meta/workspaces',
                headers=self.headers
            )
            response.raise_for_status()
            time.sleep(self.rate_limit_delay)
            return response.json()['workspaces']
        except Exception as e:
            logging.error(f"Failed to fetch workspaces: {e}")
            raise

    def get_workspace_bases(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Fetch all bases in a workspace"""
        try:
            response = requests.get(
                f'https://api.airtable.com/v0/meta/workspaces/{workspace_id}/bases',
                headers=self.headers
            )
            response.raise_for_status()
            time.sleep(self.rate_limit_delay)
            return response.json()['bases']
        except Exception as e:
            logging.error(f"Failed to fetch bases for workspace {workspace_id}: {e}")
            raise

    def get_base_schema(self, base_id: str) -> Dict[str, Any]:
        """Fetch schema for a specific base"""
        try:
            response = requests.get(
                f'https://api.airtable.com/v0/meta/bases/{base_id}/tables',
                headers=self.headers
            )
            response.raise_for_status()
            time.sleep(self.rate_limit_delay)
            return response.json()
        except Exception as e:
            logging.error(f"Failed to fetch schema for base {base_id}: {e}")
            raise

    def sanitize_name(self, name: str) -> str:
        """Sanitize a name for PostgreSQL (remove/replace special characters)"""
        sanitized = ''.join(c if c.isalnum() else '_' for c in name)
        while '__' in sanitized:
            sanitized = sanitized.replace('__', '_')
        sanitized = sanitized.strip('_')
        return sanitized.lower()

    def map_airtable_type_to_postgres(self, airtable_type: str) -> str:
        """Map Airtable field types to PostgreSQL types"""
        type_mapping = {
            # Basic types
            'singleLineText': 'TEXT',
            'multilineText': 'TEXT',
            'richText': 'TEXT',
            'number': 'NUMERIC',
            'checkbox': 'BOOLEAN',
            'singleSelect': 'TEXT',
            'multipleSelects': 'JSONB',
            'date': 'DATE',
            'dateTime': 'TIMESTAMP WITH TIME ZONE',
            'email': 'TEXT',
            'url': 'TEXT',
            'phone': 'TEXT',
            'currency': 'NUMERIC',
            'percent': 'NUMERIC',
            'autoNumber': 'SERIAL',
            'rating': 'INTEGER',

            # Complex types that need JSON storage
            'formula': 'JSONB',
            'rollup': 'JSONB',
            'lookup': 'JSONB',
            'multipleRecordLinks': 'JSONB',
            'singleRecordLink': 'JSONB',
            'attachment': 'JSONB',
            'barcode': 'JSONB',
            'button': 'JSONB',

            # System fields
            'createdTime': 'TIMESTAMP WITH TIME ZONE',
            'lastModifiedTime': 'TIMESTAMP WITH TIME ZONE',
            'createdBy': 'JSONB',
            'lastModifiedBy': 'JSONB'
        }
        return type_mapping.get(airtable_type, 'TEXT')

    def convert_value_for_postgres(self, value: Any) -> Any:
        """Convert a value to a PostgreSQL-compatible format"""
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        elif isinstance(value, bool):
            return value
        elif value is None:
            return None
        elif isinstance(value, (int, float)):
            return value
        else:
            return str(value)

    def create_postgres_table(self, workspace_name: str, base_name: str, table_name: str, fields: List[Dict[str, Any]]):
        """Create PostgreSQL table based on Airtable schema"""
        safe_workspace = self.sanitize_name(workspace_name)
        safe_base = self.sanitize_name(base_name)
        safe_table = self.sanitize_name(table_name)
        full_table_name = f"{safe_workspace}_{safe_base}_{safe_table}"

        # Create table SQL
        columns = []
        for field in fields:
            field_name = self.sanitize_name(field['name'])
            field_type = self.map_airtable_type_to_postgres(field['type'])
            columns.append(f'"{field_name}" {field_type}')

        create_table_sql = f"""
        CREATE TABLE IF NOT EXISTS {full_table_name} (
            id TEXT PRIMARY KEY,
            {', '.join(columns)}
        )
        """

        try:
            self.cur.execute(create_table_sql)
            self.conn.commit()
            logging.info(f"Created table {full_table_name}")
        except Exception as e:
            logging.error(f"Failed to create table {full_table_name}: {e}")
            self.conn.rollback()
            raise

    def sync_table_data(self, base_id: str, workspace_name: str, base_name: str, table_name: str):
        """Sync data from Airtable table to PostgreSQL"""
        safe_workspace = self.sanitize_name(workspace_name)
        safe_base = self.sanitize_name(base_name)
        safe_table = self.sanitize_name(table_name)
        full_table_name = f"{safe_workspace}_{safe_base}_{safe_table}"

        try:
            # Fetch all records
            url = f'https://api.airtable.com/v0/{base_id}/{table_name}'
            records = []
            offset = None

            while True:
                params = {'offset': offset} if offset else {}
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                data = response.json()
                records.extend(data['records'])

                if 'offset' in data:
                    offset = data['offset']
                    time.sleep(self.rate_limit_delay)
                else:
                    break

            logging.info(f"Found {len(records)} records in table {table_name}")

            # Insert records
            for record in records:
                fields = record['fields']
                sanitized_fields = {}

                for key, value in fields.items():
                    sanitized_key = self.sanitize_name(key)
                    sanitized_fields[sanitized_key] = self.convert_value_for_postgres(value)

                columns = ['id'] + list(sanitized_fields.keys())
                values = [record['id']] + list(sanitized_fields.values())

                column_list = ', '.join(f'"{col}"' for col in columns)
                placeholder_list = ', '.join(['%s'] * len(values))
                update_list = ', '.join(f'"{col}" = EXCLUDED."{col}"' for col in columns[1:]) if len(columns) > 1 else 'id = EXCLUDED.id'

                insert_sql = f'INSERT INTO {full_table_name} ({column_list}) VALUES ({placeholder_list}) ON CONFLICT (id) DO UPDATE SET {update_list}'

                self.cur.execute(insert_sql, values)

            self.conn.commit()
            logging.info(f"Synced {len(records)} records to {full_table_name}")
        except Exception as e:
            logging.error(f"Failed to sync table {full_table_name}: {e}")
            self.conn.rollback()
            raise

    def sync_all(self):
        """Main sync function"""
        try:
            self.connect_to_postgres()

            # Get all workspaces
            workspaces = self.get_all_workspaces()
            logging.info(f"Found {len(workspaces)} workspaces")

            for workspace in workspaces:
                workspace_id = workspace['id']
                workspace_name = workspace['name']
                logging.info(f"Processing workspace: {workspace_name}")

                # Get all bases in workspace
                bases = self.get_workspace_bases(workspace_id)
                logging.info(f"Found {len(bases)} bases in workspace {workspace_name}")

                for base in bases:
                    base_id = base['id']
                    base_name = base['name']
                    logging.info(f"Processing base: {base_name}")

                    # Get base schema
                    schema = self.get_base_schema(base_id)

                    for table in schema['tables']:
                        table_name = table['name']
                        logging.info(f"Processing table: {table_name}")

                        # Create table
                        self.create_postgres_table(workspace_name, base_name, table_name, table['fields'])

                        # Sync data
                        self.sync_table_data(base_id, workspace_name, base_name, table_name)

        except Exception as e:
            logging.error(f"Sync failed: {e}")
            raise
        finally:
            if self.cur:
                self.cur.close()
            if self.conn:
                self.conn.close()

def main():
    try:
        # Verify environment variables
        required_vars = [
            'AIRTABLE_TOKEN',
            'POSTGRES_DB',
            'POSTGRES_USER',
            'POSTGRES_PASSWORD',
            'POSTGRES_HOST',
            'POSTGRES_PORT'
        ]

        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        # Run sync
        syncer = AirtableToPostgres()
        syncer.sync_all()

    except Exception as e:
        logging.error(f"Application failed: {e}")
        raise

if __name__ == '__main__':
    main()
