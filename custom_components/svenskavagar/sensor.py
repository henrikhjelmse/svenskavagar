import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS, CONF_TYPE, CONF_SCAN_INTERVAL
from .const import DOMAIN
import requests
from datetime import datetime, timedelta

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up sensors based on a config entry."""
    latitude = entry.data[CONF_LATITUDE]
    longitude = entry.data[CONF_LONGITUDE]
    radius = entry.data[CONF_RADIUS]
    type_selection = entry.data[CONF_TYPE]
    activity_option = entry.data["activity_option"]
    scan_interval = entry.data[CONF_SCAN_INTERVAL]

    road_data = await hass.async_add_executor_job(
        fetch_road_data, latitude, longitude, radius, type_selection
    )
    sensors = [RoadSensor(road, entry.data) for road in road_data]

    async_add_entities(sensors, True)

def fetch_road_data(latitude, longitude, radius, type_selection):
    url = f"https://henrikhjelm.se/api/vagar.php?lat={latitude}&long={longitude}&radius={radius}"
    response = requests.get(url)
    data = response.json()
    if type_selection == "Visa alla":
        return data.get('road', [])
    else:
        return [road for road in data.get('road', []) if road['subcategory'] == type_selection]

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

    def update(self):
        current_time = datetime.now()
        
        # Check if it's time to update based on scan_interval
        if current_time - self._last_update < self._scan_interval:
            return

        self._last_update = current_time
        created_date = datetime.strptime(self._road['createddate'], '%Y-%m-%d %H:%M:%S')

        # Handle activity filtering
        if self._activity_option == "show_only_active":
            if not self._road.get('active', True):  # If road is not active
                self.hass.async_create_task(self.async_remove())
                return
        else:
            weeks = int(self._activity_option.split('_')[1])  # Extract number from 'week_X'
            if current_time - created_date > timedelta(weeks=weeks):
                self.hass.async_create_task(self.async_remove())
                return

        # Fetch the latest data
        road_data = fetch_road_data(
            self._road['latitude'],
            self._road['longitude'],
            self._config[CONF_RADIUS],  # Use configured radius
            self._config[CONF_TYPE]
        )
        # Update state with new data if available
        for r in road_data:
            if r['id'] == self._road['id']:
                self._road = r
                self._state = r['createddate']  # Changed from description to createddate
                break
        else:
            # Road is no longer available
            self.hass.async_create_task(self.async_remove())

    async def async_remove(self):
        """Remove entity."""
        await super().async_remove()
        _LOGGER.info(f"Sensor {self._attr_name} removed")
