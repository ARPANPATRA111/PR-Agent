#!/usr/bin/env python3

import sys
import argparse
import asyncio
from pathlib import Path

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))


async def set_webhook(url: str, token: str) -> dict:
    import httpx
    
    webhook_url = f"{url.rstrip('/')}/webhook"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/setWebhook",
            json={
                "url": webhook_url,
                "allowed_updates": ["message"]
            }
        )
        return response.json()


async def get_webhook_info(token: str) -> dict:
    import httpx
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.telegram.org/bot{token}/getWebhookInfo"
        )
        return response.json()


async def delete_webhook(token: str) -> dict:
    import httpx
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/deleteWebhook"
        )
        return response.json()


async def get_bot_info(token: str) -> dict:
    import httpx
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.telegram.org/bot{token}/getMe"
        )
        return response.json()


def main():
    parser = argparse.ArgumentParser(
        description="Configure Telegram webhook for Weekly Progress Agent"
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Webhook URL (e.g., https://your-app.railway.app)"
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Get current webhook info"
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete current webhook"
    )
    parser.add_argument(
        "--token",
        help="Telegram bot token (or set TELEGRAM_BOT_TOKEN env var)"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Weekly Progress Agent - Telegram Webhook Setup")
    print("=" * 60)
    
    import os
    token = args.token or os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not token:
        try:
            from config import settings
            token = settings.telegram_bot_token
        except ImportError:
            pass
    
    if not token or token == "your_telegram_bot_token_here":
        print("\n❌ Error: Telegram bot token not found!")
        print("   Set TELEGRAM_BOT_TOKEN environment variable or use --token")
        print("   Or configure it in backend/.env file")
        return 1
    
    if ":" not in token:
        print("\n❌ Error: Invalid token format!")
        print("   Token should be in format: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
        return 1
    
    print(f"\n🤖 Using bot token: {token[:10]}...{token[-5:]}")
    
    print("\n📡 Fetching bot info...")
    try:
        bot_info = asyncio.run(get_bot_info(token))
        if bot_info.get("ok"):
            bot = bot_info["result"]
            print(f"   ✓ Bot: @{bot.get('username')} ({bot.get('first_name')})")
        else:
            print(f"   ❌ Error: {bot_info.get('description', 'Unknown error')}")
            return 1
    except Exception as e:
        import traceback
        print(f"   ❌ Connection error: {type(e).__name__}: {e}")
        traceback.print_exc()
        return 1
    
    if args.info:
        print("\n📋 Getting webhook info...")
        result = asyncio.run(get_webhook_info(token))
        
        if result.get("ok"):
            info = result["result"]
            print(f"\n   URL: {info.get('url') or '(not set)'}")
            print(f"   Pending updates: {info.get('pending_update_count', 0)}")
            print(f"   Last error: {info.get('last_error_message', 'None')}")
            if info.get("last_error_date"):
                from datetime import datetime
                error_time = datetime.fromtimestamp(info["last_error_date"])
                print(f"   Last error time: {error_time}")
        else:
            print(f"   ❌ Error: {result.get('description')}")
        
        return 0
    
    if args.delete:
        print("\n🗑️ Deleting webhook...")
        result = asyncio.run(delete_webhook(token))
        
        if result.get("ok"):
            print("   ✓ Webhook deleted successfully")
        else:
            print(f"   ❌ Error: {result.get('description')}")
            return 1
        
        return 0
    
    if not args.url:
        print("\n❌ Error: URL is required!")
        print("   Usage: python setup_webhook.py https://your-domain.com")
        print("   Or use --info to see current webhook")
        return 1
    
    url = args.url
    if not url.startswith("https://"):
        print("\n⚠️ Warning: Telegram requires HTTPS for webhooks!")
        print("   Your URL should start with https://")
        
        if url.startswith("http://"):
            url = url.replace("http://", "https://")
            print(f"   Changed to: {url}")
    
    print(f"\n🔗 Setting webhook to: {url}/webhook")
    result = asyncio.run(set_webhook(url, token))
    
    if result.get("ok"):
        print("   ✓ Webhook set successfully!")
        
        print("\n📋 Verifying webhook...")
        info = asyncio.run(get_webhook_info(token))
        if info.get("ok"):
            current_url = info["result"].get("url")
            print(f"   ✓ Active URL: {current_url}")
    else:
        print(f"   ❌ Error: {result.get('description')}")
        return 1
    
    print("\n" + "=" * 60)
    print("✅ Webhook setup complete!")
    print("=" * 60)
    
    print("\nYour bot is ready to receive messages!")
    print("Test it by sending a voice note to your bot on Telegram.")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
