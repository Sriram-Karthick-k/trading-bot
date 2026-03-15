"""
Tests for Provider Registry.
"""

import pytest

from app.providers.base import ProviderError
from app.providers.registry import (
    register_provider,
    get_provider,
    set_active_provider,
    get_active_provider,
    list_providers,
    clear_registry,
)
from app.providers.mock.provider import MockProvider


class TestProviderRegistry:
    def setup_method(self):
        clear_registry()

    def teardown_method(self):
        clear_registry()

    def test_register_and_get(self):
        register_provider("test_mock", MockProvider)
        result = get_provider("test_mock")
        assert isinstance(result, MockProvider)

    def test_get_nonexistent_raises(self):
        with pytest.raises(ProviderError):
            get_provider("nonexistent")

    def test_set_active_provider(self):
        register_provider("test_mock", MockProvider)
        set_active_provider("test_mock")
        active = get_active_provider()
        assert isinstance(active, MockProvider)

    def test_list_providers(self):
        register_provider("mock1", MockProvider)
        providers = list_providers()
        assert "mock1" in providers

    def test_clear_registry(self):
        register_provider("test", MockProvider)
        clear_registry()
        with pytest.raises(ProviderError):
            get_provider("test")
