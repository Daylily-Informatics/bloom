"""Mobile UI baseline checks for modern Bloom templates/assets."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent


class TestModernMobileAssets:
    """Verify modern UI keeps core mobile-friendly contracts."""

    def test_modern_css_exists_and_has_media_queries(self):
        css_path = PROJECT_ROOT / "static" / "modern" / "css" / "bloom_modern.css"
        assert css_path.exists()
        css = css_path.read_text()
        assert "@media" in css
        assert "max-width" in css

    def test_modern_js_exists(self):
        js_path = PROJECT_ROOT / "static" / "modern" / "js" / "bloom_modern.js"
        assert js_path.exists()

    def test_base_template_has_viewport_and_modern_css(self):
        base_path = PROJECT_ROOT / "templates" / "modern" / "base.html"
        assert base_path.exists()
        content = base_path.read_text()
        assert 'name="viewport"' in content
        assert "bloom_modern.css" in content
