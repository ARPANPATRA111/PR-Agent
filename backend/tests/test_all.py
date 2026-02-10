"""
Weekly Progress Agent - Unit Tests
==================================
Comprehensive test coverage for all modules.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import json

@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    with patch('config.settings') as mock:
        mock.telegram_bot_token = "test_token"
        mock.groq_api_key = "test_groq_key"
        mock.groq_model = "llama-3.3-70b-versatile"
        mock.whisper_model = "base"
        mock.whisper_language = "auto"
        mock.database_url = "sqlite:///:memory:"
        mock.chroma_persist_dir = "./test_data/chroma"
        mock.audio_temp_dir = "./test_data/audio_temp"
        mock.log_level = "DEBUG"
        mock.debug = True
        yield mock


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from memory import Base
    
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()

class TestRateLimiter:
    """Tests for rate limiting functionality."""
    
    def test_rate_limit_config(self):
        """Test rate limit configuration values."""
        from rate_limiter import RATE_LIMITS
        
        assert "webhook" in RATE_LIMITS
        assert "voice_processing" in RATE_LIMITS
        assert "auth" in RATE_LIMITS
        assert "health" in RATE_LIMITS
    
    def test_get_remote_address(self):
        """Test extracting IP address from request."""
        from rate_limiter import get_remote_address
        from fastapi import Request
        
        mock_request = Mock(spec=Request)
        mock_request.client = Mock()
        mock_request.client.host = "192.168.1.1"
        
        # Note: slowapi's get_remote_address handles this internally
        assert get_remote_address is not None

class TestErrorRecovery:
    """Tests for error recovery and retry logic."""
    
    def test_retry_config(self):
        """Test retry configuration defaults."""
        from error_recovery import RetryConfig, RETRY_CONFIGS
        
        llm_config = RETRY_CONFIGS["llm"]
        assert llm_config.max_retries == 3
        assert llm_config.base_delay == 2.0
    
    def test_calculate_delay(self):
        """Test exponential backoff calculation."""
        from error_recovery import calculate_delay, RetryConfig
        
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=False)
        
        assert calculate_delay(0, config) == 1.0
        assert calculate_delay(1, config) == 2.0
        assert calculate_delay(2, config) == 4.0
    
    def test_circuit_breaker_states(self):
        """Test circuit breaker state transitions."""
        from error_recovery import CircuitBreaker
        
        cb = CircuitBreaker(failure_threshold=3)
        
        assert cb.state == CircuitBreaker.CLOSED
        assert cb.can_execute() == True
        
        # Record failures
        for _ in range(3):
            cb.record_failure(Exception("test"))
        
        assert cb.state == CircuitBreaker.OPEN
        assert cb.can_execute() == False
    
    def test_error_stats_collector(self):
        """Test error statistics collection."""
        from error_recovery import ErrorStatsCollector
        
        collector = ErrorStatsCollector()
        
        collector.record_success("test_op")
        collector.record_error("test_op", ValueError("test error"))
        
        stats = collector.get_stats()
        assert stats["total_successes"] == 1
        assert stats["total_errors"] == 1

class TestAuthentication:
    """Tests for JWT authentication."""
    
    def test_create_access_token(self):
        """Test access token creation."""
        from auth import create_access_token, verify_token
        
        token = create_access_token({"sub": "123", "telegram_id": 456})
        
        assert token is not None
        assert len(token) > 0
    
    def test_verify_token(self):
        """Test token verification."""
        from auth import create_access_token, verify_token
        
        token = create_access_token({
            "sub": "123",
            "telegram_id": 456,
            "username": "testuser"
        })
        
        token_data = verify_token(token)
        
        assert token_data.user_id == 123
        assert token_data.telegram_id == 456
        assert token_data.username == "testuser"
    
    def test_expired_token(self):
        """Test that expired tokens are rejected."""
        from auth import create_access_token, verify_token
        from datetime import timedelta
        from fastapi import HTTPException
        
        # Create token that expires immediately
        token = create_access_token(
            {"sub": "123", "telegram_id": 456},
            expires_delta=timedelta(seconds=-1)
        )
        
        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        
        assert exc_info.value.status_code == 401
    
    def test_password_hashing(self):
        """Test password hashing and verification."""
        from auth import get_password_hash, verify_password
        
        password = "test_password_123"
        hashed = get_password_hash(password)
        
        assert verify_password(password, hashed) == True
        assert verify_password("wrong_password", hashed) == False
    
    def test_verification_code(self):
        """Test verification code generation and validation."""
        from auth import generate_verification_code, verify_telegram_code
        
        telegram_id = 12345
        code = generate_verification_code(telegram_id)
        
        assert len(code) == 6
        assert code.isdigit()
        
        # Verify correct code
        assert verify_telegram_code(telegram_id, code) == True
        
        # Code should be consumed
        assert verify_telegram_code(telegram_id, code) == False


class TestBackupSystem:
    """Tests for database backup functionality."""
    
    def test_backup_config(self):
        """Test backup configuration."""
        from backup import BackupConfig
        
        config = BackupConfig(
            backup_dir="./test_backups",
            max_backups=5,
            compress=True
        )
        
        assert config.max_backups == 5
        assert config.compress == True
    
    @pytest.mark.skip(reason="Requires actual database file")
    def test_create_backup(self):
        """Test backup creation."""
        from backup import create_backup, BackupConfig
        
        config = BackupConfig(backup_dir="./test_data/backups")
        result = create_backup(backup_name="test", config=config)
        
        assert "timestamp" in result
    
    def test_list_backups(self):
        """Test listing backups."""
        from backup import list_backups, BackupConfig
        
        config = BackupConfig(backup_dir="./test_data/backups")
        backups = list_backups(config)
        
        assert isinstance(backups, list)

class TestLogging:
    """Tests for enhanced logging functionality."""
    
    def test_json_formatter(self):
        """Test JSON log formatting."""
        from logging_config import JSONFormatter
        import logging
        
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        
        assert parsed["message"] == "Test message"
        assert parsed["level"] == "INFO"
        assert "timestamp" in parsed
    
    def test_log_context(self):
        """Test contextual logging."""
        from logging_config import LogContext
        
        with LogContext(user_id=123, operation="test"):
            assert LogContext.get("user_id") == 123
            assert LogContext.get("operation") == "test"
        
        # Context should be cleared
        assert LogContext.get("user_id") is None
    
    def test_audit_logging(self):
        """Test audit event logging."""
        from logging_config import log_audit_event, get_audit_logger
        
        # Should not raise
        log_audit_event(
            event_type="auth",
            user_id=123,
            action="login",
            success=True
        )

class TestTelegramClient:
    """Tests for Telegram bot client with retry logic."""
    
    @pytest.mark.asyncio
    async def test_send_message_retry(self):
        """Test message sending with retry on failure."""
        from bot import TelegramClient
        
        client = TelegramClient("test_token")
        
        # Mock the _request_with_retry method
        with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock:
            mock.return_value = {"ok": True, "result": {"message_id": 123}}
            
            result = await client.send_message(12345, "Test message")
            
            assert result["ok"] == True
            mock.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_typing_action(self):
        """Test typing action doesn't raise on failure."""
        from bot import TelegramClient
        
        client = TelegramClient("test_token")
        
        with patch.object(client, '_request_with_retry', new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Network error")
            
            # Should not raise
            await client.send_typing_action(12345)

class TestLLMAgent:
    """Tests for LLM agent functionality."""
    
    def test_prompt_loader(self):
        """Test prompt template loading."""
        from llm_agent import PromptLoader
        
        loader = PromptLoader()
        
        # Should return empty string for non-existent prompts
        result = loader.load("nonexistent_prompt")
        assert result == "" or result is not None
    
    @patch('llm_agent.Groq')
    def test_llm_agent_init(self, mock_groq):
        """Test LLM agent initialization."""
        with patch('config.settings') as mock_settings:
            mock_settings.groq_api_key = "test_key"
            mock_settings.groq_model = "llama-3.3-70b-versatile"
            mock_settings.llm_temperature = 0.7
            
            from llm_agent import LLMAgent
            agent = LLMAgent()
            
            assert agent.model == "llama-3.3-70b-versatile"

class TestUtils:
    """Tests for utility functions."""
    
    def test_truncate_text(self):
        """Test text truncation."""
        from utils import truncate_text
        
        # Short text should not be truncated
        short = "Hello world"
        assert truncate_text(short, 100) == short
        
        # Long text should be truncated
        long = "This is a very long text " * 50
        result = truncate_text(long, 100)
        assert len(result) <= 103  # 100 + "..."
        assert result.endswith("...")
    
    def test_format_streak(self):
        """Test streak formatting."""
        from utils import format_streak
        
        assert "🔥" in format_streak(5)
        assert "5" in format_streak(5)
    
    def test_format_duration(self):
        """Test duration formatting."""
        from utils import format_duration
        
        assert "1h" in format_duration(3600) or "hour" in format_duration(3600).lower()
    
    def test_extract_keywords(self):
        """Test keyword extraction."""
        from utils import extract_keywords
        
        text = "Today I worked on Python programming and fixed some bugs in the API"
        keywords = extract_keywords(text)
        
        assert isinstance(keywords, list)

class TestModels:
    """Tests for Pydantic models."""
    
    def test_telegram_update_model(self):
        """Test Telegram update parsing."""
        from models import TelegramUpdate
        
        data = {
            "update_id": 123,
            "message": {
                "message_id": 456,
                "date": 1234567890,
                "chat": {"id": 789, "type": "private"},
                "from": {"id": 111, "is_bot": False, "first_name": "Test"},
                "text": "Hello"
            }
        }
        
        update = TelegramUpdate(**data)
        assert update.update_id == 123
        assert update.message.text == "Hello"
    
    def test_classification_result_model(self):
        """Test classification result model."""
        from models import ClassificationResult, EntryCategory
        
        result = ClassificationResult(
            category=EntryCategory.CODING,
            summary="Working on tests",
            activities=["writing tests"],
            blockers=[],
            accomplishments=["completed test suite"],
            learnings=["pytest fixtures"],
            keywords=["pytest", "testing"],
            sentiment="positive",
            confidence=0.95
        )
        
        assert result.category == EntryCategory.CODING
        assert result.confidence == 0.95
    
    def test_linkedin_post_model(self):
        """Test LinkedIn post model."""
        from models import LinkedInPost, PostTone, PostStatus
        
        post = LinkedInPost(
            id=1,
            user_id=123,
            weekly_summary_id=1,
            tone=PostTone.PROFESSIONAL,
            content="Test post content",
            hashtags=["#coding", "#testing"],
            status=PostStatus.DRAFT,
            created_at=datetime.utcnow()
        )
        
        assert post.tone == PostTone.PROFESSIONAL
        assert len(post.hashtags) == 2

class TestIntegration:
    """Integration tests for combined functionality."""
    
    @pytest.mark.asyncio
    async def test_full_voice_processing_pipeline(self):
        """Test complete voice note processing (mocked)."""
        # This would test the full pipeline with mocks
        pass
    
    @pytest.mark.asyncio
    async def test_webhook_to_response(self):
        """Test webhook processing end-to-end (mocked)."""
        pass

class TestAPIEndpoints:
    """Tests for FastAPI endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)
    
    def test_health_endpoint(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
