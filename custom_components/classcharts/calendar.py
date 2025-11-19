"""Calendar platform for ClassCharts."""

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from pyclasscharts import ParentClient
from pyclasscharts.exceptions import AuthenticationError, ValidationError
from pyclasscharts.types import Lesson, Pupil

from . import ClassChartsCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ClassCharts calendar entities."""
    coordinator: ClassChartsCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create a calendar entity for each pupil
    entities = []
    for pupil_id, pupil in coordinator.data.items():
        entities.append(
            ClassChartsCalendarEntity(
                coordinator=coordinator,
                pupil_id=pupil_id,
                pupil=pupil,
                entry_id=entry.entry_id,
            )
        )

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
        self._pupil_id = pupil_id
        self._pupil = pupil
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{pupil_id}"
        self._attr_name = "Timetable"
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
        
        # Create a client for this pupil
        client = self.coordinator.get_client_for_pupil(self._pupil_id)
        
        try:
            # Login and select pupil
            await hass.async_add_executor_job(client.login)
            await hass.async_add_executor_job(client.select_pupil, self._pupil_id)
            
            # Fetch lessons for each day in the range
            current_date = start_date_time.date()
            end_date = end_date_time.date()
            
            while current_date <= end_date:
                try:
                    date_str = current_date.strftime("%Y-%m-%d")
                    lessons_response = await hass.async_add_executor_job(
                        client.get_lessons,
                        {"date": date_str}
                    )
                    
                    for lesson in lessons_response.get("data", []):
                        event = self._lesson_to_event(lesson, current_date)
                        if event:
                            events.append(event)
                except Exception:  # noqa: BLE001
                    # Skip days that fail, continue with next day
                    pass
                
                current_date += timedelta(days=1)
                
        except (AuthenticationError, ValidationError):
            # Return empty list on auth errors
            return []
        except Exception:  # noqa: BLE001
            # Return empty list on other errors
            return []

        return events

    def _lesson_to_event(self, lesson: Lesson, lesson_date: date) -> CalendarEvent | None:
        """Convert a lesson to a CalendarEvent."""
        try:
            # Parse start and end times
            start_time_str = lesson.get("start_time", "")
            end_time_str = lesson.get("end_time", "")
            
            if not start_time_str or not end_time_str:
                return None
            
            # Parse time (format is typically HH:MM)
            try:
                start_hour, start_minute = map(int, start_time_str.split(":"))
                end_hour, end_minute = map(int, end_time_str.split(":"))
            except (ValueError, AttributeError):
                return None
            
            start_datetime = datetime.combine(
                lesson_date,
                time(hour=start_hour, minute=start_minute),
            )
            end_datetime = datetime.combine(
                lesson_date,
                time(hour=end_hour, minute=end_minute),
            )
            
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
        except Exception:  # noqa: BLE001
            return None

