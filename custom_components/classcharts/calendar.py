"""Calendar platform for ClassCharts."""

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import parse_datetime

from pyclasscharts import ParentClient
from pyclasscharts.exceptions import AuthenticationError, ValidationError
from pyclasscharts.types import Lesson, Pupil

from . import ClassChartsCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ClassCharts calendar entities."""
    coordinator: ClassChartsCoordinator = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.debug(
        "Setting up calendar entities. Coordinator data: %s",
        coordinator.data,
    )

    # Create a calendar entity for each pupil
    entities = []
    for pupil_id, pupil in coordinator.data.items():
        _LOGGER.info(
            "Creating calendar entity for pupil: %s (ID: %s)",
            pupil.get("name", "Unknown"),
            pupil_id,
        )
        entities.append(
            ClassChartsCalendarEntity(
                coordinator=coordinator,
                pupil_id=pupil_id,
                pupil=pupil,
                entry_id=entry.entry_id,
            )
        )

    _LOGGER.info("Created %d calendar entities", len(entities))
    async_add_entities(entities)


class ClassChartsCalendarEntity(
    CoordinatorEntity[ClassChartsCoordinator], CalendarEntity
):
    """ClassCharts calendar entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ClassChartsCoordinator,
        pupil_id: int,
        pupil: Pupil,
        entry_id: str,
    ) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        pupil_name = pupil.get("name", f"Pupil {pupil_id}")

        self._pupil_id = pupil_id
        self._pupil = pupil
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{pupil_id}_timetable"
        self._attr_name = f"Timetable"
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

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self._update_device_info()

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        return None  # Calendar will fetch events as needed

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date_time: datetime,
        end_date_time: datetime,
    ) -> list[CalendarEvent]:
        """Get all events in a specific time frame."""
        events: list[CalendarEvent] = []
        pupil_name = self._pupil.get("name", "Unknown") if self._pupil else "Unknown"
        
        _LOGGER.debug(
            "Fetching events for pupil %s (ID: %s) from %s to %s",
            pupil_name,
            self._pupil_id,
            start_date_time,
            end_date_time,
        )

        # Fetch lessons for each day in the range
        current_date = start_date_time.date()
        end_date = end_date_time.date()
            
        lessons_data = await self.coordinator.get_lesson_data_for_pupil_between_dates(self._pupil_id, current_date, end_date)
        for lesson in lessons_data:
            try:
                # Parse the lesson date from the lesson dict
                lesson_date = datetime.strptime(lesson["date"], "%Y-%m-%d").date()
            except (ValueError, KeyError) as err:
                _LOGGER.debug(
                    "Skipping lesson due to invalid or missing date: %s, error: %s",
                    lesson,
                    err
                )
                continue

            event = self._lesson_to_event(lesson, lesson_date)
            if event:
                events.append(event)
                _LOGGER.debug(
                    "Created event: %s at %s",
                    event.summary,
                    event.start,
                )
            else:
                _LOGGER.debug(
                    "Failed to convert lesson to event: %s",
                    lesson,
                )
        
        return events

    def _lesson_to_event(self, lesson: Lesson, lesson_date: date) -> CalendarEvent | None:
        """Convert a lesson to a CalendarEvent."""
        try:
            # Parse start and end times
            start_time_str = lesson.get("start_time", "")
            end_time_str = lesson.get("end_time", "")
            
            if not start_time_str or not end_time_str:
                _LOGGER.debug(
                    "Lesson missing time data: start_time=%s, end_time=%s, lesson=%s",
                    start_time_str,
                    end_time_str,
                    lesson,
                )
                return None
            
            try:
                start_datetime = parse_datetime(start_time_str)
                end_datetime = parse_datetime(end_time_str)
            except (ValueError, AttributeError) as err:
                _LOGGER.debug(
                    "Failed to parse time: start_time=%s, end_time=%s, error=%s",
                    start_time_str,
                    end_time_str,
                    err,
                )
                return None
            # # Parse time (format is typically HH:MM)
            # try:    
            #     start_hour, start_minute = map(int, start_time_str.split(":"))
            #     end_hour, end_minute = map(int, end_time_str.split(":"))
            # except (ValueError, AttributeError) as err:
            #     _LOGGER.debug(
            #         "Failed to parse time: start_time=%s, end_time=%s, error=%s",
            #         start_time_str,
            #         end_time_str,
            #         err,
            #     )
            #     return None
            
            # start_datetime = datetime.combine(
            #     lesson_date,
            #     time(hour=start_hour, minute=start_minute),
            # )
            # end_datetime = datetime.combine(
            #     lesson_date,
            #     time(hour=end_hour, minute=end_minute),
            # )
            
            # Build event title
            subject = lesson.get("subject_name", "Unknown Subject")
            lesson_name = lesson.get("lesson_name", "")
            if lesson_name and lesson_name != subject:
                title = f"{subject} - {lesson_name}"
            else:
                title = subject
            
            # Build description
            description_parts = []
            if lesson.get("teacher_name"):
                description_parts.append(f"Teacher: {lesson['teacher_name']}")
            if lesson.get("room_name"):
                description_parts.append(f"Room: {lesson['room_name']}")
            if lesson.get("period_name"):
                description_parts.append(f"Period: {lesson['period_name']}")
            if lesson.get("note"):
                description_parts.append(f"Note: {lesson['note']}")
            if lesson.get("pupil_note"):
                description_parts.append(f"Your Note: {lesson['pupil_note']}")
            
            description = "\n".join(description_parts) if description_parts else None
            
            return CalendarEvent(
                start=start_datetime,
                end=end_datetime,
                summary=title,
                description=description,
                location=lesson.get("room_name"),
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "Error converting lesson to event: %s, error=%s",
                lesson,
                err,
                exc_info=True,
            )
            return None

