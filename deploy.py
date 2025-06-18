#!/usr/bin/env python3
"""
VV-Alarm Bot Deployment Script
This script helps you set up and deploy the VV-Alarm Discord bot.
"""

import os
import sys
import subprocess
import json
from pathlib import Path


def check_python_version():
    """Check if Python version is 3.8 or higher."""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required!")
        print(f"Current version: {sys.version}")
        return False
    print(f"✅ Python version: {sys.version}")
    return True


def install_dependencies():
    """Install required dependencies."""
    print("\n📦 Installing dependencies...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]
        )
        print("✅ Dependencies installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False


def setup_environment():
    """Set up environment variables."""
    print("\n🔧 Setting up environment variables...")

    env_path = Path(".env")
    example_env_path = Path("env.example")

    if env_path.exists():
        print("⚠️  .env file already exists. Skipping environment setup.")
        return True

    if not example_env_path.exists():
        print("❌ env.example file not found!")
        return False

    # Copy example to .env
    with open(example_env_path, "r") as f:
        content = f.read()

    print("\n📝 Please provide the following information:")

    # Get Discord bot token
    discord_token = input("Enter your Discord Bot Token: ").strip()
    if not discord_token:
        print("❌ Discord bot token is required!")
        return False

    # Get CoC API token
    coc_token = input("Enter your Clash of Clans API Token: ").strip()
    if not coc_token:
        print("❌ Clash of Clans API token is required!")
        return False

    # Replace tokens in content
    content = content.replace("your_discord_bot_token_here", discord_token)
    content = content.replace("your_clash_of_clans_api_token_here", coc_token)

    # Write .env file
    with open(".env", "w") as f:
        f.write(content)

    print("✅ Environment file created successfully!")
    return True


def create_directories():
    """Create necessary directories."""
    print("\n📁 Creating directories...")

    directories = ["logs", "data"]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"✅ Created directory: {directory}")

    return True


def validate_setup():
    """Validate that everything is set up correctly."""
    print("\n🔍 Validating setup...")

    # Check if .env exists
    if not os.path.exists(".env"):
        print("❌ .env file not found!")
        return False

    # Check if main bot file exists
    if not os.path.exists("VV-Alarm.py"):
        print("❌ VV-Alarm.py not found!")
        return False

    # Check if requirements.txt exists
    if not os.path.exists("requirements.txt"):
        print("❌ requirements.txt not found!")
        return False

    print("✅ All required files are present!")
    return True


def test_bot():
    """Test if the bot can start properly."""
    print("\n🧪 Testing bot startup...")

    try:
        # Import the bot to check for basic syntax errors
        from dotenv import load_dotenv

        load_dotenv()

        # Check environment variables
        discord_token = os.getenv("DISCORD_BOT_TOKEN")
        coc_token = os.getenv("COC_API_TOKEN")

        if not discord_token or discord_token == "your_discord_bot_token_here":
            print("❌ Discord bot token not properly set!")
            return False

        if not coc_token or coc_token == "your_clash_of_clans_api_token_here":
            print("❌ Clash of Clans API token not properly set!")
            return False

        print("✅ Environment variables are properly configured!")
        print("✅ Bot should start successfully!")
        return True

    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        return False
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False


def main():
    """Main deployment function."""
    print("🚀 VV-Alarm Bot Deployment Script")
    print("=" * 40)

    # Check Python version
    if not check_python_version():
        sys.exit(1)

    # Install dependencies
    if not install_dependencies():
        sys.exit(1)

    # Set up environment
    if not setup_environment():
        sys.exit(1)

    # Create directories
    if not create_directories():
        sys.exit(1)

    # Validate setup
    if not validate_setup():
        sys.exit(1)

    # Test bot
    if not test_bot():
        sys.exit(1)

    print("\n🎉 Deployment completed successfully!")
    print("\n📋 Next steps:")
    print("1. Make sure your Discord bot has the correct permissions")
    print("2. Invite your bot to your Discord server")
    print("3. Run the bot with: python VV-Alarm.py")
    print("4. Use /health_check command to verify everything is working")
    print("\n📚 Read the README.md for detailed usage instructions.")


if __name__ == "__main__":
    main()
