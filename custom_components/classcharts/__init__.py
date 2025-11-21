"""The ClassCharts integration."""

import logging
from datetime import date, timedelta
from typing import Any, Dict, List

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from pyclasscharts import ParentClient
from pyclasscharts.exceptions import AuthenticationError, ValidationError
from pyclasscharts.types import Pupil

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]

SCAN_INTERVAL = timedelta(hours=1)


class ClassChartsCoordinator(DataUpdateCoordinator[Dict[int, Pupil]]):
    """ClassCharts data coordinator."""

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_method=self._async_update_data,
            update_interval=SCAN_INTERVAL,
        )
        self.client = ParentClient(email, password)
        self._email = email
        self._password = password
        # keyed by pupil_id -> pupil data
        self._pupils: Dict[int, Pupil   ] = {}
        # keyed by pupil_id -> dict[date, list]
        self._timetable_cache: Dict[int, Dict[date, List[Any]]] = {}

    async def _async_update_data(self) -> Dict[int, Pupil]:
        """Fetch data from ClassCharts."""
        try:
            if not await self.login():
                raise UpdateFailed("Error fetching ClassCharts data, login failed")

            _LOGGER.debug("Fetching pupils list")
            pupils_list = await self.hass.async_add_executor_job(self.client.get_pupils)

            _LOGGER.debug("Received %d pupils from API", len(pupils_list) if pupils_list else 0)
            if pupils_list:
                _LOGGER.debug("Pupils data: %s", pupils_list)

            # Convert to dict keyed by pupil ID
            pupils_dict: dict[int, Pupil] = {pupil["id"]: pupil for pupil in pupils_list}

            self._pupils = pupils_dict

            _LOGGER.info(
                "Successfully fetched %d pupils: %s",
                len(pupils_dict),
                [p.get("name", "Unknown") for p in pupils_dict.values()],
            )

            # Fetch and cache 8 days (today + next 7) of timetable lessons for each pupil
            for pupil_id in pupils_dict.keys():
                # ensure cache entry exists
                self._timetable_cache.setdefault(pupil_id, {})

                # prune old entries
                self.prune_cache_for_pupil(pupil_id)

                start_date = date.today()
                dates = [start_date + timedelta(days=i) for i in range(8)]

                # cache_lesson_data_for_pupil_for_dates is async because it does IO
                await self._cache_lesson_data_for_pupil_for_dates(pupil_id, dates)

            return pupils_dict
        except (AuthenticationError, ValidationError) as err:
            _LOGGER.error(
                "Authentication/validation error fetching ClassCharts data: %s",
                err,
                exc_info=True,
            )
            raise UpdateFailed(f"Error fetching ClassCharts data: {err}") from err
        except Exception as err:
            _LOGGER.error(
                "Unexpected error fetching ClassCharts data: %s",
                err,
                exc_info=True,
            )
            raise UpdateFailed(f"Unexpected error fetching ClassCharts data: {err}") from err

    async def login(self) -> bool:
        """Perform login using executor to avoid blocking the event loop."""
        try:
            _LOGGER.debug("Logging in to ClassCharts for email: %s", self._email)
            # run blocking login in executor
            await self.hass.async_add_executor_job(self.client.login)
        except (AuthenticationError, ValidationError) as err:
            _LOGGER.error("Authentication/validation error: %s", err)
            return False
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Unexpected error logging in: %s", err, exc_info=True)
            return False
        return True

    async def select_pupil(self, pupil_id: int) -> bool:
        """Select the pupil on the remote API (if required by the client)."""
        try:
            _LOGGER.debug("Selecting pupil %s", pupil_id)
            await self.hass.async_add_executor_job(self.client.select_pupil, pupil_id)
        except AuthenticationError as err:
            _LOGGER.error("Authentication error selecting pupil %s: %s", pupil_id, err)
            return False
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Unexpected error selecting pupil %s: %s", pupil_id, err, exc_info=True)
            return False
        return True

    async def get_lesson_data_for_pupil_between_dates(
        self, pupil_id: int, start_date: date, end_date: date
    ) -> List[Any]:
        """Return lessons for a pupil between two dates (uses cache)."""
        lessons_all: List[Any] = []
        dates = [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]

        # ensure cache entry exists
        self._timetable_cache.setdefault(pupil_id, {})

        uncached_dates = [d for d in dates if d not in self._timetable_cache.get(pupil_id, {})]

        # populate cache for any missing dates (this may trigger login/select_pupil)
        await self._cache_lesson_data_for_pupil_for_dates(pupil_id, uncached_dates)

        for d in dates:
            pupil_cache = self._timetable_cache.get(pupil_id, {})
            if d in pupil_cache:
                lessons_all.extend(pupil_cache[d])
        return lessons_all

    def prune_cache_for_pupil(self, pupil_id: int) -> None:
        """Remove cached entries older than 7 days for a given pupil."""
        cache = self._timetable_cache.get(pupil_id, {})
        cutoff = date.today() - timedelta(days=7)
        self._timetable_cache[pupil_id] = {d: v for d, v in cache.items() if d >= cutoff}

    async def _cache_lesson_data_for_pupil_for_dates(self, pupil_id: int, dates: List[date]) -> None:
        """Fetch lessons for the given pupil/dates and cache them."""

        if not await self.select_pupil(pupil_id):
            _LOGGER.error("Selecting pupil %s failed; aborting lesson cache", pupil_id)
            return

        for d in dates:
            try:
                date_str = d.strftime("%Y-%m-%d")
                _LOGGER.debug("Fetching lessons for pupil %s date %s", pupil_id, date_str)

                lessons_response = await self.hass.async_add_executor_job(
                    self.client.get_lessons, {"date": date_str}
                )

                _LOGGER.debug("Lessons response for %s: %s", date_str, lessons_response)

                lessons_data = lessons_response.get("data", []) if lessons_response else []
                _LOGGER.debug("Found %d lessons for %s", len(lessons_data), date_str)

                # ensure pupil cache exists again (concurrent safety)
                self._timetable_cache.setdefault(pupil_id, {})
                self._timetable_cache[pupil_id][d] = lessons_data

                _LOGGER.debug("Cached %d lessons for pupil ID %s on %s", len(lessons_data), pupil_id, date_str)

            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Error fetching lessons for pupil %s date %s: %s", pupil_id, d, err, exc_info=True
                )
                # continue to next date on failure

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ClassCharts from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    _LOGGER.info("Setting up ClassCharts integration for email: %s", email)

    coordinator = ClassChartsCoordinator(hass, email, password)

    # Fetch initial data
    _LOGGER.debug("Performing initial coordinator refresh")
    await coordinator.async_config_entry_first_refresh()

    _LOGGER.debug(
        "Coordinator data after refresh: %s pupils",
        len(coordinator.data) if coordinator.data else 0,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    _LOGGER.debug("Forwarding setup to platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("ClassCharts integration setup complete")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
