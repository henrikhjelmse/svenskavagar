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
    show_only_active = entry.data.get("show_only_active", True)

    road_data = await hass.async_add_executor_job(
        fetch_road_data, 
        latitude, 
        longitude, 
        radius, 
        type_selection,
        show_only_active
    )
    
    sensors = [RoadSensor(road, entry.data, weeks_active) for road in road_data]
    async_add_entities(sensors, True)

def fetch_road_data(latitude, longitude, radius, type_selection, show_only_active=True):
    url = f"https://henrikhjelm.se/api/vagar.php?lat={latitude}&long={longitude}&radius={radius}"
    response = requests.get(url)
    data = response.json()
    roads = data.get('road', [])
    
    # Filter active status if needed
    if show_only_active:
        roads = [road for road in roads if road.get('aktiv', False)]
    
    # Filter by type if needed
    if type_selection != "Visa alla":
        roads = [road for road in roads if road['subcategory'] == type_selection]
    
    return roads

class RoadSensor(SensorEntity):
    def __init__(self, road, config, weeks_active):
        self._road = road
        self._config = config
        self._weeks_active = weeks_active
        self._attr_name = road['title']
        self._attr_unique_id = str(road['id'])
        self._attr_icon = "mdi:alert"
        self._update_state()

    def _update_state(self):
        # Set only the creation date as the state
        self._state = self._road['createddate']

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def extra_state_attributes(self):
        return {
            "priority": self._road['priority'],
            "createddate": self._road['createddate'],
            "description": self._road['description'],
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
            self._config[CONF_RADIUS],
            self._config[CONF_TYPE],
            self._config.get("show_only_active", True)
        )
        
        # Update state with new data if available
        for r in road_data:
            if r['id'] == self._road['id']:
                if not r.get('aktiv', False) and self._config.get("show_only_active", True):
                    self.hass.async_create_task(self.async_remove())
                    return
                self._road = r
                self._update_state()
                break
        else:
            # Road is no longer available
            self.hass.async_create_task(self.async_remove())

    async def async_remove(self):
        """Remove entity."""
        await super().async_remove()
        _LOGGER.info(f"Sensor {self._attr_name} removed")
