import logging
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS, CONF_TYPE
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
    weeks_active = entry.data["weeks_active"]

    road_data = await hass.async_add_executor_job(
        fetch_road_data, latitude, longitude, radius, type_selection
    )
    sensors = [RoadSensor(road, entry.data, weeks_active) for road in road_data]

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
    def __init__(self, road, config, weeks_active):
        self._road = road
        self._config = config
        self._weeks_active = weeks_active
        self._attr_name = road['title']
        self._attr_unique_id = str(road['id'])
        title = road['title']
        description = road['description']
        self._state = f"Title: {title}\nDescription: {description}"
        self._attr_icon = "mdi:alert"

    @property
    def extra_state_attributes(self):
        return {
            "priority": self._road['priority'],
            "createddate": self._road['createddate'],
            "description": self._road['description'],  # Added missing comma here
            "latitude": self._road['latitude'],
            "longitude": self._road['longitude'],
            "category": self._road['category'],
            "subcategory": self._road['subcategory'],
        }

    def update(self):
        created_date = datetime.strptime(self._road['createddate'], '%Y-%m-%d %H:%M:%S')
        current_date = datetime.now()
        if current_date - created_date > timedelta(weeks=self._weeks_active):
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
                self._state = r['description']
                break
        else:
            # Road is no longer available
            self.hass.async_create_task(self.async_remove())

    async def async_remove(self):
        """Remove entity."""
        await super().async_remove()
        _LOGGER.info(f"Sensor {self._attr_name} removed")
