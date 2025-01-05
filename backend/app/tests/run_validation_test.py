#!/usr/bin/env python3
import sys
import os
import asyncio

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from backend.app.tests.test_validation import main

if __name__ == "__main__":
    asyncio.run(main())
