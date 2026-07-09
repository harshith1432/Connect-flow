import os
import sys
from sqlalchemy import create_engine, MetaData, select
from sqlalchemy.orm import sessionmaker

# Add the parent directory to sys.path so we can import 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from dotenv import load_dotenv

def migrate_data(source_uri: str, target_uri: str):
    """
    Migrates data from a source database to a target database.
    Handles table creation and foreign key insertion order.
    """
    print(f"[*] Initializing Migration...")
    print(f"[*] Source Database: {source_uri}")
    print(f"[*] Target Database: {target_uri}")

    # Set the target database for the Flask app to create tables
    os.environ['DATABASE_URL'] = target_uri
    app = create_app()

    with app.app_context():
        # 1. Create all tables in the target database
        print("[*] Creating tables in target database (if they don't exist)...")
        db.create_all()
        target_engine = db.engine
        TargetSession = sessionmaker(bind=target_engine)

        # 2. Connect to the source database
        print("[*] Connecting to source database...")
        source_engine = create_engine(source_uri)
        source_metadata = MetaData()
        source_metadata.reflect(bind=source_engine)
        SourceSession = sessionmaker(bind=source_engine)

        with SourceSession() as src_session, TargetSession() as tgt_session:
            # 3. Iterate over tables in topological order (handles Foreign Keys)
            print("[*] Starting data transfer...")
            
            # Disable foreign key checks on Target for PostgreSQL if needed
            if target_engine.dialect.name == 'postgresql':
                tgt_session.execute(db.text("SET session_replication_role = 'replica';"))

            try:
                for table in source_metadata.sorted_tables:
                    print(f"    -> Migrating table: {table.name}...", end=" ")
                    
                    # Fetch all rows from source
                    rows = src_session.execute(select(table)).fetchall()
                    if not rows:
                        print("Skipped (0 rows)")
                        continue

                    # Clear existing data in target (Optional: comment out if appending)
                    # tgt_session.execute(table.delete())
                    
                    # Convert rows to list of dicts for bulk insert
                    # Handle SQLite specific dialect issues (like booleans as 0/1 to True/False) if necessary
                    # SQLAlchemy usually abstracts this well if tables are reflected accurately.
                    records = []
                    for row in rows:
                        record = dict(row._mapping)
                        records.append(record)

                    # Insert into target
                    tgt_engine_table = db.metadata.tables.get(table.name)
                    if tgt_engine_table is not None:
                        tgt_session.execute(tgt_engine_table.insert(), records)
                        print(f"Migrated {len(records)} rows")
                    else:
                        print("Failed (Table not found in target schema)")

                # Commit changes
                tgt_session.commit()
                print("\n[+] Migration completed successfully!")

            except Exception as e:
                tgt_session.rollback()
                print(f"\n[-] Migration failed: {e}")
                raise

            finally:
                # Re-enable foreign key checks for PostgreSQL
                if target_engine.dialect.name == 'postgresql':
                    tgt_session.execute(db.text("SET session_replication_role = 'origin';"))
                    tgt_session.commit()

if __name__ == "__main__":
    load_dotenv()
    
    # Define source and target URIs
    # SQLite is usually local: sqlite:///instance/dev.db
    # Supabase Postgres URL should be placed in TARGET_DATABASE_URL in .env
    
    SOURCE_DB = os.environ.get("SOURCE_DATABASE_URL", "sqlite:///instance/dev.db")
    
    # If the user hasn't provided TARGET_DATABASE_URL, use DATABASE_URL from .env
    TARGET_DB = os.environ.get("TARGET_DATABASE_URL")
    if not TARGET_DB:
        TARGET_DB = os.environ.get("DATABASE_URL")
        
    if not TARGET_DB:
        print("[-] Error: TARGET_DATABASE_URL or DATABASE_URL is missing from environment variables.")
        sys.exit(1)

    if SOURCE_DB == TARGET_DB:
        print("[-] Error: Source and Target database URLs are identical. Aborting.")
        sys.exit(1)

    migrate_data(SOURCE_DB, TARGET_DB)
