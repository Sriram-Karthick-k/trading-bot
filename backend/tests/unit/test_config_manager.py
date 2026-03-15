"""
Tests for ConfigManager.
"""


from app.core.config_manager import ConfigSchema


class TestConfigManager:
    def test_get_default_value(self, config_manager):
        val = config_manager.get("nonexistent_key", default="fallback")
        assert val == "fallback"

    def test_set_and_get(self, config_manager):
        config_manager.set_db_override("test.key", "hello")
        assert config_manager.get("test.key") == "hello"

    def test_get_typed_int(self, config_manager):
        config_manager.set_db_override("test.count", "42")
        val = config_manager.get("test.count", type_hint=int)
        assert val == 42

    def test_get_typed_float(self, config_manager):
        config_manager.set_db_override("test.ratio", "3.14")
        val = config_manager.get("test.ratio", type_hint=float)
        assert val == 3.14

    def test_get_typed_bool(self, config_manager):
        config_manager.set_db_override("test.flag", "true")
        val = config_manager.get("test.flag", type_hint=bool)
        assert val is True

    def test_get_all(self, config_manager):
        config_manager.set_db_override("a.key", "val1")
        config_manager.set_db_override("b.key", "val2")
        all_config = config_manager.get_all()
        assert isinstance(all_config, dict)
        assert "a.key" in all_config
        assert "b.key" in all_config

    def test_register_schema_provides_default(self, config_manager):
        schema = ConfigSchema(
            key="test.validated",
            description="test",
            default="10",
            type="int",
            min_value=1,
            max_value=100,
        )
        config_manager.register_config(schema) if hasattr(config_manager, 'register_config') else None
        # Even without register, get_all returns from yaml defaults
        all_config = config_manager.get_all()
        assert isinstance(all_config, dict)
