from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
import sqlite3
import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, text
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_alembic_config():
    """Get Alembic configuration."""
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "backend/migrations")
    alembic_cfg.set_main_option("sqlalchemy.url", "sqlite:///backend/xauto.db")
    return alembic_cfg

def create_migration_files():
    """Create initial migration files if they don't exist."""
    migrations_dir = "backend/migrations"
    versions_dir = os.path.join(migrations_dir, "versions")
    
    try:
        # Create migrations directory if it doesn't exist
        os.makedirs(versions_dir, exist_ok=True)

        # Create env.py if it doesn't exist
        env_py = os.path.join(migrations_dir, "env.py")
        if not os.path.exists(env_py):
            env_content = '''from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys

# Add parent directory to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Import Base and all models
from backend.app.database import Base
from backend.app.models.account import Account

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()'''
            with open(env_py, "w") as f:
                f.write(env_content)

        # Create script.py.mako if it doesn't exist
        script_mako = os.path.join(migrations_dir, "script.py.mako")
        if not os.path.exists(script_mako):
            mako_content = '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade():
    ${upgrades if upgrades else "pass"}

def downgrade():
    ${downgrades if downgrades else "pass"}'''
            with open(script_mako, "w") as f:
                f.write(mako_content)

    except Exception as e:
        logger.error(f"Error creating migration files: {e}")
        raise

def init_alembic():
    """Initialize Alembic if not already initialized."""
    try:
        create_migration_files()
        
        # Get Alembic config
        alembic_cfg = get_alembic_config()
        
        # Check if alembic_version table exists
        engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"))
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            if not context.get_current_revision():
                logger.info("Initializing Alembic...")
                # Create initial migration
                command.revision(alembic_cfg, "Initial migration", autogenerate=True)
                logger.info("Created initial migration")
                
                # Apply migration
                command.upgrade(alembic_cfg, "head")
                logger.info("Applied initial migration")
    except Exception as e:
        logger.error(f"Error initializing Alembic: {e}")
        raise

def migrate_database():
    """Run all database migrations."""
    try:
        # Ensure database directory exists
        os.makedirs("backend", exist_ok=True)

        # Initialize Alembic and create initial migration
        init_alembic()

        # Get Alembic config
        alembic_cfg = get_alembic_config()

        # Create new migration for additional columns
        command.revision(alembic_cfg, "Add tracking columns", autogenerate=True)
        logger.info("Created migration for tracking columns")
        
        # Apply all migrations
        command.upgrade(alembic_cfg, "head")
        logger.info("Applied all migrations")

        # Set default values for timestamps
        engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"))
        with engine.connect() as conn:
            now = datetime.utcnow().isoformat()
            conn.execute(text("""
                UPDATE accounts 
                SET created_at = :now, 
                    updated_at = :now 
                WHERE created_at IS NULL
            """), {"now": now})
            conn.commit()

        logger.info("Database migration completed successfully")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

def check_migration_status():
    """Check current migration status."""
    try:
        # Get Alembic config
        alembic_cfg = get_alembic_config()
        
        # Get current revision
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()
        
        # Get database revision
        engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url"))
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_revision = context.get_current_revision()
        
        if current_revision == head_revision:
            logger.info("Database is up to date")
            return True
        else:
            logger.warning(f"Database needs migration. Current: {current_revision}, Head: {head_revision}")
            return False
    except Exception as e:
        logger.error(f"Error checking migration status: {e}")
        return False

if __name__ == "__main__":
    command_name = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    
    if command_name == "init":
        init_alembic()
    elif command_name == "create":
        alembic_cfg = get_alembic_config()
        command.revision(alembic_cfg, "New migration", autogenerate=True)
    elif command_name == "upgrade":
        migrate_database()
    elif command_name == "status":
        check_migration_status()
    else:
        print("Unknown command. Use: init, create, upgrade, or status")
