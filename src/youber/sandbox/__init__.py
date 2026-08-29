"""Módulo sandbox de BARF: simulaciones aisladas para estudio educativo.

Contiene simulaciones de geolocalización/idioma/zona horaria, condiciones de
red y dispositivos, pensadas para estudiar cómo responden las webs a distintos
entornos. Todo el tráfico generado aquí es de bajo volumen y con fines
educativos.
"""

from youber.sandbox.device import get_device_options, simulate_device
from youber.sandbox.geolocation import get_region_options, simulate_location, test_localization
from youber.sandbox.network import get_speed_options, simulate_network, test_performance

__all__ = [
    "get_device_options",
    "get_region_options",
    "get_speed_options",
    "simulate_device",
    "simulate_location",
    "simulate_network",
    "test_localization",
    "test_performance",
]
