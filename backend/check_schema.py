import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, inspect
from backend.app.database import Base
from backend.app.models.profile_update import ProfileUpdate

# Create engine
engine = create_engine('sqlite:///app.db')

# Create tables
Base.metadata.create_all(engine)

# Create inspector
inspector = inspect(engine)

# Get columns for profile_updates table
columns = inspector.get_columns('profile_updates')

# Print column information
for column in columns:
    print(f"Column: {column['name']}, Type: {column['type']}")
