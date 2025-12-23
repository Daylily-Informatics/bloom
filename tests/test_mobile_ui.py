"""
Tests for Mobile UI CSS and JavaScript

These tests verify that mobile UI assets are properly structured
and contain required responsive design elements.
"""

import os
import re
from pathlib import Path

import pytest


# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


class TestMobileCSS:
    """Tests for mobile.css responsive stylesheet."""

    @pytest.fixture
    def mobile_css_content(self):
        """Load mobile.css content."""
        css_path = PROJECT_ROOT / "static" / "mobile.css"
        assert css_path.exists(), "mobile.css not found"
        return css_path.read_text()

    def test_mobile_css_exists(self):
        """Test that mobile.css file exists."""
        css_path = PROJECT_ROOT / "static" / "mobile.css"
        assert css_path.exists()

    def test_contains_mobile_breakpoint(self, mobile_css_content):
        """Test that mobile breakpoint is defined."""
        assert "--mobile-breakpoint" in mobile_css_content or "768px" in mobile_css_content

    def test_contains_touch_target_size(self, mobile_css_content):
        """Test that minimum touch target size is defined."""
        # Apple HIG recommends 44px minimum
        assert "--mobile-touch-target" in mobile_css_content or "44px" in mobile_css_content

    def test_contains_media_queries(self, mobile_css_content):
        """Test that responsive media queries are present."""
        assert "@media" in mobile_css_content
        assert "max-width" in mobile_css_content

    def test_contains_touch_friendly_button_styles(self, mobile_css_content):
        """Test that touch-friendly button styles are defined."""
        assert "button" in mobile_css_content.lower()
        assert "min-height" in mobile_css_content

    def test_contains_responsive_table_styles(self, mobile_css_content):
        """Test that responsive table styles are present."""
        assert "table" in mobile_css_content.lower()
        assert "overflow" in mobile_css_content

    def test_contains_safe_area_insets(self, mobile_css_content):
        """Test that safe area insets are handled for notched devices."""
        assert "safe-area-inset" in mobile_css_content

    def test_contains_header_responsive_styles(self, mobile_css_content):
        """Test that header has responsive styles."""
        assert "header-container" in mobile_css_content

    def test_contains_floating_button_mobile_styles(self, mobile_css_content):
        """Test that floating buttons have mobile adjustments."""
        assert "floating-button" in mobile_css_content


class TestMobileJS:
    """Tests for mobile.js JavaScript enhancements."""

    @pytest.fixture
    def mobile_js_content(self):
        """Load mobile.js content."""
        js_path = PROJECT_ROOT / "static" / "mobile.js"
        assert js_path.exists(), "mobile.js not found"
        return js_path.read_text()

    def test_mobile_js_exists(self):
        """Test that mobile.js file exists."""
        js_path = PROJECT_ROOT / "static" / "mobile.js"
        assert js_path.exists()

    def test_contains_mobile_detection(self, mobile_js_content):
        """Test that mobile device detection is implemented."""
        assert "isMobile" in mobile_js_content

    def test_contains_touch_event_handling(self, mobile_js_content):
        """Test that touch events are handled."""
        assert "touchstart" in mobile_js_content
        assert "touchend" in mobile_js_content

    def test_contains_swipe_detection(self, mobile_js_content):
        """Test that swipe gesture detection is present."""
        assert "swipe" in mobile_js_content.lower()

    def test_contains_responsive_tables_init(self, mobile_js_content):
        """Test that responsive table initialization is present."""
        assert "initResponsiveTables" in mobile_js_content

    def test_contains_debounce_utility(self, mobile_js_content):
        """Test that debounce utility is present."""
        assert "debounce" in mobile_js_content

    def test_exports_bloom_mobile_object(self, mobile_js_content):
        """Test that BloomMobile object is exported."""
        assert "window.BloomMobile" in mobile_js_content

    def test_auto_initializes(self, mobile_js_content):
        """Test that mobile enhancements auto-initialize."""
        assert "init()" in mobile_js_content


class TestTemplatesMobileIntegration:
    """Tests for mobile assets integration in HTML templates."""

    def test_index2_includes_mobile_css(self):
        """Test that index2.html includes mobile.css."""
        template_path = PROJECT_ROOT / "templates" / "index2.html"
        content = template_path.read_text()
        assert "mobile.css" in content

    def test_index2_includes_mobile_js(self):
        """Test that index2.html includes mobile.js."""
        template_path = PROJECT_ROOT / "templates" / "index2.html"
        content = template_path.read_text()
        assert "mobile.js" in content

    def test_index2_has_viewport_meta(self):
        """Test that index2.html has viewport meta tag."""
        template_path = PROJECT_ROOT / "templates" / "index2.html"
        content = template_path.read_text()
        assert 'viewport' in content
        assert 'width=device-width' in content

    def test_dewey_includes_mobile_assets(self):
        """Test that dewey.html includes mobile assets."""
        template_path = PROJECT_ROOT / "templates" / "dewey.html"
        content = template_path.read_text()
        assert "mobile.css" in content
        assert "mobile.js" in content

    def test_admin_includes_mobile_assets(self):
        """Test that admin.html includes mobile assets."""
        template_path = PROJECT_ROOT / "templates" / "admin.html"
        content = template_path.read_text()
        assert "mobile.css" in content
        assert "mobile.js" in content

    def test_templates_have_apple_mobile_web_app_meta(self):
        """Test that templates have Apple mobile web app meta tags."""
        template_path = PROJECT_ROOT / "templates" / "index2.html"
        content = template_path.read_text()
        assert "apple-mobile-web-app-capable" in content

