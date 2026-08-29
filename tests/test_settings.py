"""Tests básicos de la configuración del framework."""

from youber.settings import Settings, get_settings


def test_defaults_from_env():
    settings = Settings.from_env()
    assert settings.browser_headless is False
    assert settings.browser_timeout == 30000
    assert settings.log_level == "INFO"
    assert settings.user_agent_list.name == "user_agents.json"
    # Las rutas relativas se resuelven contra la raíz del proyecto
    assert settings.user_agent_list.is_absolute()


def test_user_agent_file_exists():
    settings = Settings.from_env()
    assert settings.user_agent_list.exists(), (
        f"No se encuentra {settings.user_agent_list}"
    )


def test_get_settings_is_singleton():
    assert get_settings() is get_settings()
