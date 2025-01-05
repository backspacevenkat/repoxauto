from setuptools import setup, find_packages

setup(
    name="xauto",
    version="0.1.0",
    description="Twitter Account Management and Validation System",
    author="Xauto Team",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "fastapi==0.104.1",
        "uvicorn[standard]==0.24.0",
        "sqlalchemy==2.0.23",
        "alembic==1.12.1",
        "aiosqlite==0.19.0",
        "python-multipart==0.0.6",
        "httpx==0.25.1",
        "playwright==1.39.0",
        "2captcha-python==1.2.0",
        "pandas==2.1.3",
        "colorama==0.4.6",
        "python-jose[cryptography]==3.3.0",
        "passlib[bcrypt]==1.7.4",
        "twikit==2.2.0",
        "aiohttp==3.9.1",
        "beautifulsoup4==4.12.2",
        "pydantic==2.5.2",
        "pydantic-settings==2.1.0",
        "python-dotenv==1.0.0",
        "requests==2.31.0",
        "urllib3==2.1.0",
        "websockets==12.0"
    ],
    extras_require={
        'dev': [
            'pytest>=7.4.3',
            'pytest-asyncio>=0.21.1',
            'pytest-cov>=4.1.0',
            'black>=23.11.0',
            'isort>=5.12.0',
            'mypy>=1.7.1',
            'flake8>=6.1.0'
        ]
    },
    entry_points={
        'console_scripts': [
            'xauto=backend.app.main:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Operating System :: OS Independent',
        'Topic :: Internet :: WWW/HTTP',
        'Framework :: FastAPI',
        'Framework :: AsyncIO',
    ],
)
