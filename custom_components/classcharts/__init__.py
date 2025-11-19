"""The ClassCharts integration."""

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from pyclasscharts import ParentClient
from pyclasscharts.exceptions import AuthenticationError, ValidationError
from pyclasscharts.types import Pupil

from .const import DOMAIN

PLATFORMS: list[Platform] = [Platform.CALENDAR]

SCAN_INTERVAL = timedelta(hours=1)


class ClassChartsCoordinator(DataUpdateCoordinator[dict[int, Pupil]]):
    """ClassCharts data coordinator."""

    def __init__(self, hass: HomeAssistant, email: str, password: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.client = ParentClient(email, password)
        self._email = email
        self._password = password
        self._pupils: dict[int, Pupil] = {}

    async def _async_update_data(self) -> dict[int, Pupil]:
        """Fetch data from ClassCharts."""
        try:
            # Login if needed (session may have expired)
            await self.hass.async_add_executor_job(self.client.login)
            
            # Get pupils
            pupils_list = await self.hass.async_add_executor_job(self.client.get_pupils)
            
            # Convert to dict keyed by pupil ID
            pupils_dict: dict[int, Pupil] = {pupil["id"]: pupil for pupil in pupils_list}
            self._pupils = pupils_dict
            
            return pupils_dict
        except (AuthenticationError, ValidationError) as err:
            raise UpdateFailed(f"Error fetching ClassCharts data: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Unexpected error fetching ClassCharts data: {err}") from err

    def get_client_for_pupil(self, pupil_id: int) -> ParentClient:
        """Get a client configured for a specific pupil."""
        # Create a new client instance for this pupil
        client = ParentClient(self._email, self._password)
        # We'll need to login and select the pupil when needed
        return client


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up ClassCharts from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    coordinator = ClassChartsCoordinator(hass, email, password)
    
    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

