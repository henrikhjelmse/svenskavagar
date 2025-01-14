import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS, CONF_TYPE, CONF_SCAN_INTERVAL
from .const import DOMAIN, CONF_PREFIX
import requests
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors based on a config entry."""
    try:
        latitude = entry.data[CONF_LATITUDE]
        longitude = entry.data[CONF_LONGITUDE]
        radius = entry.data[CONF_RADIUS]
        type_selection = entry.data[CONF_TYPE]
        scan_interval = entry.data[CONF_SCAN_INTERVAL]

        _LOGGER.debug(f"Setting up sensor with lat:{latitude}, long:{longitude}, radius:{radius}")
        
        road_data = await hass.async_add_executor_job(
            fetch_road_data, latitude, longitude, radius, type_selection
        )
        
        if not road_data:
            _LOGGER.warning("No road data received from API")
            return
            
        sensors = [RoadSensor(road, entry.data) for road in road_data]
        _LOGGER.debug(f"Created {len(sensors)} sensors")
        
        async_add_entities(sensors, True)
        return True
        
    except Exception as ex:
        _LOGGER.error(f"Error setting up sensor: {ex}")
        return False

def fetch_road_data(latitude, longitude, radius, type_selection):
    try:
        url = f"https://henrikhjelm.se/api/vagar.php?lat={latitude}&long={longitude}&radius={radius}"
        _LOGGER.debug(f"Fetching data from: {url}")
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        roads = data.get('road', [])
        
        # Filter out inactive roads if they exist in the API response
        active_roads = [road for road in roads if road.get('active', True)]
        _LOGGER.debug(f"Found {len(active_roads)} active roads")
        
        if type_selection == "Visa alla":
            return active_roads
        
        filtered_roads = [road for road in active_roads if road['subcategory'] == type_selection]
        _LOGGER.debug(f"Filtered to {len(filtered_roads)} roads of type {type_selection}")
        return filtered_roads
        
    except Exception as ex:
        _LOGGER.error(f"Error fetching road data: {ex}")
        return []

class RoadSensor(SensorEntity):
    def __init__(self, road, config):
        self._road = road
        self._config = config
        prefix = config.get(CONF_PREFIX, "")
        self._attr_name = f"{prefix} {road['title']}" if prefix else road['title']
        self._attr_unique_id = str(road['id'])
        self._state = road['createddate']
        self._attr_icon = "mdi:alert"
        self._scan_interval = timedelta(minutes=config[CONF_SCAN_INTERVAL])
        self._last_update = datetime.now()

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        return {
            "description": self._road['description'],
            "priority": self._road['priority'],
            "createddate": self._road['createddate'],
            "exactlocation": self._road['exactlocation'],
            "latitude": self._road['latitude'],
            "longitude": self._road['longitude'],
            "category": self._road['category'],
            "subcategory": self._road['subcategory'],
        }

    async def async_update(self):
        """Async update method."""
        current_time = datetime.now()
        
        if current_time - self._last_update < self._scan_interval:
            return

        self._last_update = current_time
        
        road_data = await self.hass.async_add_executor_job(
            fetch_road_data,
            self._road['latitude'],
            self._road['longitude'],
            self._config[CONF_RADIUS],
            self._config[CONF_TYPE]
        )

        # Check if the road still exists and is active
        road_still_exists = False
        for r in road_data:
            if r['id'] == self._road['id']:
                if r.get('active', True) is False:  # Check if road became inactive
                    _LOGGER.debug(f"Road {self._attr_name} became inactive")
                    await self.async_remove()
                    return
                road_still_exists = True
                self._road = r
                self._state = r['createddate']
                break

        if not road_still_exists:
            _LOGGER.debug(f"Road {self._attr_name} is no longer available")
            await self.async_remove()
            return

    def update(self):
        """Legacy update method - not used."""
        return

    async def async_remove(self):
        """Remove entity."""
        await super().async_remove()
        _LOGGER.info(f"Sensor {self._attr_name} removed")
