import os
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Razorpay Agentic Merchant System"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "test"
    
    # Razorpay Settings (Test Mode)
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "rzp_test_mock_merchant_key")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "mock_merchant_secret_998877")
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "whsec_mock_razorpay_secret_123")
    
    # Merchant Admin Auth
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "razorpay_agent_secure_2026")
    
    # Agent Auth & Mandates
    AGENT_AUTH_SECRET: str = os.getenv("AGENT_AUTH_SECRET", "agent_shared_master_secret_2026")
    
    # Policy Engine Bounds & Defaults
    DAILY_MERCHANT_SPEND_CAP_INR: float = 10000000.0  # ₹1 Crore daily merchant ceiling
    DEFAULT_APPROVAL_THRESHOLD_INR: float = 50000.0
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 30
    
    # LLM Settings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./merchant.db")
    
    # Mock fallback flag for Razorpay SDK calls in test/sandbox
    USE_MOCK_RAZORPAY_FALLBACK: bool = True

settings = Settings()
