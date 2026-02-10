#!/usr/bin/env python3

import sys
import os
from pathlib import Path

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

os.chdir(backend_dir)


def main():
    print("=" * 60)
    print("Weekly Progress Agent - Database Initialization")
    print("=" * 60)
    
    print("\n📁 Creating data directories...")
    
    directories = [
        "./data",
        "./data/audio_temp",
        "./data/logs",
        "./data/chroma",
    ]
    
    for dir_path in directories:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        print(f"   ✓ {dir_path}")
    
    print("\n🗄️ Initializing SQLite database...")
    
    try:
        from memory import Base, MemoryManager
        from config import settings
        
        manager = MemoryManager()
        
        print(f"   ✓ Database created at: {settings.database_url}")
        print(f"   ✓ ChromaDB initialized at: {settings.chroma_persist_dir}")
        
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("   Make sure you've installed dependencies:")
        print("   pip install -r requirements.txt")
        return 1
    except Exception as e:
        print(f"\n❌ Error initializing database: {e}")
        return 1
    
    print("\n📊 Verifying database tables...")
    
    try:
        from sqlalchemy import inspect
        
        inspector = inspect(manager.engine)
        tables = inspector.get_table_names()
        
        expected_tables = [
            "users",
            "raw_entries",
            "structured_entries",
            "daily_summaries",
            "weekly_summaries",
            "linkedin_posts",
            "nudge_logs"
        ]
        
        for table in expected_tables:
            if table in tables:
                print(f"   ✓ {table}")
            else:
                print(f"   ✗ {table} (MISSING)")
        
    except Exception as e:
        print(f"   ⚠️ Could not verify tables: {e}")
    
    print("\n🔧 Checking environment configuration...")
    
    env_file = backend_dir / ".env"
    if env_file.exists():
        print(f"   ✓ .env file found")
    else:
        print(f"   ⚠️ .env file not found")
        print(f"   → Copy .env.example to .env and configure it")
    
    from config import settings
    
    config_status = {
        "Telegram Bot Token": bool(settings.telegram_bot_token and settings.telegram_bot_token != "your_telegram_bot_token_here"),
        "Groq API Key": bool(settings.groq_api_key and settings.groq_api_key != "your_groq_api_key_here"),
        "Whisper Model": bool(settings.whisper_model),
    }
    
    for name, configured in config_status.items():
        if configured:
            print(f"   ✓ {name} configured")
        else:
            print(f"   ⚠️ {name} NOT configured")
    
    print("\n" + "=" * 60)
    print("✅ Database initialization complete!")
    print("=" * 60)
    
    print("\nNext steps:")
    print("1. Configure .env file with your credentials")
    print("2. Run: uvicorn main:app --reload")
    print("3. Set up Telegram webhook (see scripts/setup_webhook.py)")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
