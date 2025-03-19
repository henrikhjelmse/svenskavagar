import logging
import asyncio
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS, CONF_TYPE, CONF_SCAN_INTERVAL
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import device_registry as dr
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from .const import DOMAIN
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)  # Default scan interval

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors based on a config entry."""
    debug_mode = entry.data.get("debug_mode", False)
    scan_interval = entry.data[CONF_SCAN_INTERVAL]

    async def async_update_sensors(now=None):
        """Fetch new sensors from API."""
        if debug_mode:
            _LOGGER.debug("Checking for new sensors...")

        # Fetch all current road data
        road_data = await hass.async_add_executor_job(
            fetch_road_data,
            entry.data[CONF_LATITUDE],
            entry.data[CONF_LONGITUDE],
            entry.data[CONF_RADIUS],
            entry.data[CONF_TYPE],
            entry.data["activity_option"],
            debug_mode
        )

        # Get existing sensors
        entity_registry = er.async_get(hass)
        existing_sensors = {
            entity.unique_id.split('_')[-1]: entity
            for entity in entity_registry.entities.values()
            if entity.domain == "sensor" and entity.platform == DOMAIN
        }

        # Create new sensors for new roads
        new_sensors = []
        for road in road_data:
            if str(road['id']) not in existing_sensors:
                if debug_mode:
                    _LOGGER.debug(f"Found new road: {road['title']} (ID: {road['id']})")
                new_sensors.append(RoadSensor(road, entry.data))

        if new_sensors:
            if debug_mode:
                _LOGGER.debug(f"Adding {len(new_sensors)} new sensors")
            async_add_entities(new_sensors, True)

    # Do initial setup
    road_data = await hass.async_add_executor_job(
        fetch_road_data,
        entry.data[CONF_LATITUDE],
        entry.data[CONF_LONGITUDE],
        entry.data[CONF_RADIUS],
        entry.data[CONF_TYPE],
        entry.data["activity_option"],
        debug_mode
    )
    sensors = [RoadSensor(road, entry.data) for road in road_data]
    async_add_entities(sensors, True)

    # Schedule regular updates
    async_track_time_interval(hass, async_update_sensors, timedelta(minutes=scan_interval))

def fetch_road_data(latitude, longitude, radius, type_selection, activity_option, debug_mode=False):
    """Fetch road data from the API."""
    url = f"https://henrikhjelm.se/api/vagar.php?lat={latitude}&long={longitude}&radius={radius}"
    response = requests.get(url)
    data = response.json()
    roads = data.get('road', [])

    if debug_mode:
        _LOGGER.debug(f"Fetched {len(roads)} roads from API")
        _LOGGER.debug(f"Activity option: {activity_option}, Type selection: {type_selection}")

    # Först filtrera baserat på activity_option
    if activity_option == "show_only_active":
        active_roads = [road for road in roads if road.get('active', False) is True]
        if debug_mode:
            _LOGGER.debug(f"Filtered to {len(active_roads)} active roads from {len(roads)} total roads")
        roads = active_roads

    # Sedan filtrera baserat på type_selection om det behövs
    if type_selection != "Visa alla":
        filtered_roads = [road for road in roads if road['subcategory'] == type_selection]
        if debug_mode:
            _LOGGER.debug(f"Filtered to {len(filtered_roads)} roads of type {type_selection} from {len(roads)} roads")
        roads = filtered_roads

    return roads

class RoadSensor(SensorEntity):
    def __init__(self, road, config):
        self._road = road
        self._config = config
        self._attr_name = f"trafik_{road['title']}"  # Prefix with sensor.trafik
        self._attr_unique_id = f"sensor.trafik_{road['id']}"  # Prefix with sensor.trafik
        self._state = road['createddate']  # Changed from description to createddate
        self._attr_icon = "mdi:alert"
        self._activity_option = config["activity_option"]
        self._scan_interval = timedelta(minutes=config[CONF_SCAN_INTERVAL])
        self._last_update = datetime.now()
        self._removed = False
        self._available = True
        self._debug = config.get("debug_mode", False)
        if self._debug:
            _LOGGER.debug(f"Initializing sensor for road: {road['title']} (ID: {road['id']})")

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        return {
            "description": self._road['description'],  # Added description to attributes
            "priority": self._road['priority'],
            "createddate": self._road['createddate'],
            "exactlocation": self._road['exactlocation'],
            "latitude": self._road['latitude'],
            "longitude": self._road['longitude'],
            "category": self._road['category'],
            "subcategory": self._road['subcategory'],
        }

    async def async_update(self):
        """Update the sensor state."""
        if self._removed:
            return

        current_time = datetime.now()
        
        # First update or scheduled update
        if self._last_update is None or (current_time - self._last_update) >= self._scan_interval:
            if self._debug:
                _LOGGER.debug(f"Starting update for {self._attr_name}")
                _LOGGER.debug(f"Current road state: {self._road}")

            self.log_message("debug", f"Updating sensor {self._attr_name} at {current_time} (Interval: {self._scan_interval.total_seconds()/60} minutes)")
            self._last_update = current_time
            
            try:
                # Check if description is empty
                if not self._road.get('description'):
                    self.log_message("info", f"Removing sensor {self._attr_name} with empty description")
                    self._available = False
                    await self.remove_from_ha()
                    return
                
                created_date = datetime.strptime(self._road['createddate'], '%Y-%m-%d %H:%M:%S')
                
                # För tidbaserad filtrering
                if self._activity_option != "show_only_active":
                    weeks = int(self._activity_option.split('_')[1])
                    age = current_time - created_date
                    if age > timedelta(weeks=weeks):
                        self.log_message("info", f"Removing outdated sensor {self._attr_name}")
                        self._available = False
                        await self.remove_from_ha()
                        return

                # Update sensor data
                road_data = await self.hass.async_add_executor_job(
                    fetch_road_data,
                    self._road['latitude'],
                    self._road['longitude'],
                    self._config[CONF_RADIUS],
                    self._config[CONF_TYPE],
                    self._activity_option
                )
                
                for r in road_data:
                    if r['id'] == self._road['id']:
                        self._road = r
                        self._state = r['createddate']
                        
                        # Check if updated road has empty description
                        if not r.get('description'):
                            self.log_message("info", f"Updated road {self._attr_name} has empty description, removing")
                            await self.remove_from_ha()
                            return
                            
                        self.log_message("debug", f"Updated sensor {self._attr_name} with new data")
                        break
                else:
                    self.log_message("info", f"Road {self._attr_name} is no longer available in API response")
                    await self.remove_from_ha()
                    
            except asyncio.CancelledError:
                self.log_message("debug", f"Update cancelled for {self._attr_name}")
                raise
            except Exception as e:
                self.log_message("error", f"Error updating sensor {self._attr_name}: {e}")

            if self._debug:
                _LOGGER.debug(f"Finished update for {self._attr_name}")
                if self._road:
                    _LOGGER.debug(f"Updated road state: {self._road}")
        else:
            self.log_message("debug", f"Skipping update, next update in {(self._scan_interval - (current_time - self._last_update)).total_seconds()/60:.1f} minutes")

    async def remove_from_ha(self):
        """Remove entity completely from Home Assistant."""
        if self._removed:
            return

        self._removed = True
        self._available = False

        if self._debug:
            _LOGGER.debug(f"Starting removal process for {self._attr_name}")
            _LOGGER.debug(f"Current entity state: {self.state}")
            _LOGGER.debug(f"Entity attributes: {self.extra_state_attributes}")

        try:
            # Först ta bort från entity registry
            try:
                entity_registry = er.async_get(self.hass)
                if entity_registry.async_get(self.entity_id):
                    entity_registry.async_remove(self.entity_id)
                    self.log_message("debug", f"Removed {self._attr_name} from registry")
            except Exception as e:
                self.log_message("error", f"Error removing from registry: {e}")

            # Sedan ta bort state
            try:
                self._attr_should_poll = False
                self._attr_available = False
                self.async_write_ha_state()
                # Fix: Don't await states.async_remove as it returns a bool, not a coroutine
                self.hass.states.async_remove(self.entity_id)
                self.log_message("debug", f"Removed {self._attr_name} state")
            except Exception as e:
                self.log_message("error", f"Error removing state: {e}")

            # Ta bort från platform
            try:
                if hasattr(self, 'platform') and hasattr(self.platform, 'async_remove_entity'):
                    await self.platform.async_remove_entity(self.entity_id)
                    self.log_message("debug", f"Removed {self._attr_name} from platform")
            except Exception as e:
                self.log_message("error", f"Error removing from platform: {e}")

            # Final cleanup
            try:
                await super().async_remove()
                self.log_message("info", f"Entity {self._attr_name} completely removed")
            except Exception as e:
                self.log_message("error", f"Error in final cleanup: {e}")

            # Force refresh of entity registry
            self.hass.bus.async_fire("entity_registry_updated")
            await self.hass.async_block_till_done()

        except Exception as e:
            self.log_message("error", f"Error during removal of {self._attr_name}: {e}")
        finally:
            if self._debug:
                _LOGGER.debug(f"Completed removal process for {self._attr_name}")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    async def async_remove(self):
        """Remove entity."""
        if not self._removed:
            try:
                await super().async_remove()
                self.log_message("info", f"Entity {self._attr_name} removed successfully")
            except Exception as e:
                self.log_message("error", f"Error during entity removal of {self._attr_name}: {e}")

    def log_message(self, level, message):
        """Log a message with the specified level."""
        log_func = getattr(_LOGGER, level, _LOGGER.info)
        log_func(message)
