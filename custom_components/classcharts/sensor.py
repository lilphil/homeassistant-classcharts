"""Sensor platform for ClassCharts integration."""

from __future__ import annotations

from typing import Any
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ClassChartsCoordinator
from .const import DOMAIN


SENSORS = [
    "detention_yes_count",
    "detention_no_count",
    "detention_pending_count",
    "detention_upscaled_count",
    "homework_todo_count",
    "homework_late_count",
    "homework_not_completed_count",
    "homework_excused_count",
    "homework_completed_count",
    "homework_submitted_count",
]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ClassCharts sensor entities."""
    coordinator: ClassChartsCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for pupil_id, pupil in coordinator.data.items():

        # Create sensors
        for sensor_key in SENSORS:
            entities.append(
                ClassChartsSensorEntity(
                    coordinator=coordinator,
                    pupil_id=pupil_id,
                    pupil=pupil,
                    entry_id=entry.entry_id,
                    sensor_key=sensor_key,
                )
            )

    async_add_entities(entities)


class ClassChartsSensorEntity(SensorEntity):
    """Representation of a ClassCharts pupil detention/homework sensor."""

    def __init__(
        self,
        coordinator: ClassChartsCoordinator,
        pupil_id: int,
        pupil: Pupil,
        entry_id: str,
        sensor_key: str,
    ) -> None:
        self.coordinator = coordinator

        pupil_name = pupil.get("name", f"Pupil {pupil_id}")

        self._pupil_id = pupil_id
        self._pupil = pupil
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{pupil_id}_{sensor_key}"
        self._attr_name = f"{sensor_key.replace('_', ' ').title()}"
        self._sensor_key = sensor_key
        self._update_device_info()

    def _update_device_info(self) -> None:
        """Update device info from coordinator data."""
        pupil = self.coordinator.data.get(self._pupil_id)
        if pupil:
            self._pupil = pupil
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{self._entry_id}_{self._pupil_id}")},
                name=pupil["name"],
                manufacturer="ClassCharts",
                model="Pupil",
            )

    @property
    def native_value(self) -> Any:
        pupil = self.coordinator.data.get(self._pupil_id, {})
        return pupil.get(self._sensor_key)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._pupil_id in self.coordinator.data

    async def async_update(self) -> None:
        """Update is handled by the coordinator, so nothing to do here."""
        pass
