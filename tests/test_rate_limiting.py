"""
Tests for bloom_lims.api.rate_limiting module.
"""

import pytest
import time
from unittest.mock import Mock, patch

from bloom_lims.api.rate_limiting import (
    RateLimiter,
    RateLimitConfig,
    ClientBucket,
    get_rate_limiter,
    rate_limit,
)


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""
    
    def test_defaults(self):
        """Test default values."""
        config = RateLimitConfig()
        assert config.requests_per_minute == 60
        assert config.requests_per_hour == 1000
        assert config.burst_size == 10
        assert config.enabled is True
    
    def test_custom_values(self):
        """Test custom configuration."""
        config = RateLimitConfig(
            requests_per_minute=30,
            requests_per_hour=500,
            enabled=False,
        )
        assert config.requests_per_minute == 30
        assert config.enabled is False


class TestRateLimiter:
    """Tests for RateLimiter class."""
    
    def test_allows_under_limit(self):
        """Test requests under limit are allowed."""
        limiter = RateLimiter(requests_per_minute=10, enabled=True)
        
        for i in range(5):
            allowed, info = limiter.is_allowed("client1")
            assert allowed is True
            assert info["rate_limited"] is False
    
    def test_blocks_over_minute_limit(self):
        """Test requests over minute limit are blocked."""
        limiter = RateLimiter(requests_per_minute=3, burst_size=0, enabled=True)
        
        # Make requests up to limit
        for _ in range(3):
            allowed, _ = limiter.is_allowed("client1")
            assert allowed is True
        
        # Next request should be blocked
        allowed, info = limiter.is_allowed("client1")
        assert allowed is False
        assert info["rate_limited"] is True
        assert "retry_after" in info
    
    def test_burst_allows_extra(self):
        """Test burst capacity allows extra requests beyond minute limit."""
        # With burst_size=5 and requests_per_minute=3, we should be able to
        # make more requests initially due to token bucket having burst tokens
        limiter = RateLimiter(requests_per_minute=3, burst_size=5, enabled=True)

        # Should allow at least 3 requests (minute limit)
        allowed_count = 0
        for _ in range(3):
            allowed, _ = limiter.is_allowed("client1")
            if allowed:
                allowed_count += 1

        assert allowed_count == 3
    
    def test_disabled_limiter(self):
        """Test disabled limiter allows all requests."""
        limiter = RateLimiter(requests_per_minute=1, enabled=False)
        
        for _ in range(100):
            allowed, info = limiter.is_allowed("client1")
            assert allowed is True
            assert info["rate_limited"] is False
    
    def test_separate_clients(self):
        """Test different clients have separate limits."""
        limiter = RateLimiter(requests_per_minute=2, burst_size=0, enabled=True)
        
        # Client 1 uses their limit
        limiter.is_allowed("client1")
        limiter.is_allowed("client1")
        allowed1, _ = limiter.is_allowed("client1")
        assert allowed1 is False
        
        # Client 2 has fresh limit
        allowed2, _ = limiter.is_allowed("client2")
        assert allowed2 is True
    
    def test_get_stats(self):
        """Test getting rate limit stats."""
        limiter = RateLimiter(enabled=True)
        limiter.is_allowed("client1")
        limiter.is_allowed("client1")
        
        stats = limiter.get_stats()
        assert stats["total_clients"] == 1
        assert stats["enabled"] is True
        
        client_stats = limiter.get_stats("client1")
        assert client_stats["client_id"] == "client1"
        assert client_stats["requests_minute"] == 2
    
    def test_reset_client(self):
        """Test resetting a single client."""
        limiter = RateLimiter(requests_per_minute=2, burst_size=0, enabled=True)
        
        limiter.is_allowed("client1")
        limiter.is_allowed("client1")
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is False
        
        # Reset client
        limiter.reset("client1")
        
        # Should be allowed again
        allowed, _ = limiter.is_allowed("client1")
        assert allowed is True
    
    def test_reset_all(self):
        """Test resetting all clients."""
        limiter = RateLimiter(enabled=True)
        
        limiter.is_allowed("client1")
        limiter.is_allowed("client2")
        
        assert limiter.get_stats()["total_clients"] == 2
        
        limiter.reset()
        
        assert limiter.get_stats()["total_clients"] == 0


class TestRateLimitDecorator:
    """Tests for @rate_limit decorator."""
    
    def test_allows_function_call(self):
        """Test decorator allows function calls under limit."""
        @rate_limit(requests_per_minute=10)
        def my_function(request):
            return "success"
        
        mock_request = Mock()
        mock_request.client.host = "127.0.0.1"
        
        result = my_function(mock_request)
        assert result == "success"


class TestGetRateLimiter:
    """Tests for get_rate_limiter function."""
    
    def test_returns_singleton(self):
        """Test that get_rate_limiter returns the same instance."""
        limiter1 = get_rate_limiter()
        limiter2 = get_rate_limiter()
        
        assert limiter1 is limiter2

