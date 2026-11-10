import os
import pytest
pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    import custom_components   # le plugin de test a son propre paquet custom_components : on y ajoute le nôtre
    ici = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "custom_components"))
    if ici not in custom_components.__path__:
        custom_components.__path__.insert(0, ici)
    yield
