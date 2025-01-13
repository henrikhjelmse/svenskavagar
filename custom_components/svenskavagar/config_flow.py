import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS, CONF_TYPE, CONF_SCAN_INTERVAL
from .const import DOMAIN
import homeassistant.helpers.config_validation as cv
import aiohttp
import async_timeout
import json

async def fetch_types():
    url = "https://henrikhjelm.se/api/vagar.php?types=2"
    async with aiohttp.ClientSession() as session:
        with async_timeout.timeout(10):
            async with session.get(url) as response:
                if response.status != 200:
                    return []
                data = await response.text()
                return json.loads(data).get('types', [])

class SvenskaVagarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            # Round latitude and longitude to two decimal places
            user_input[CONF_LATITUDE] = round(float(user_input[CONF_LATITUDE]), 2)
            user_input[CONF_LONGITUDE] = round(float(user_input[CONF_LONGITUDE]), 2)

            return self.async_create_entry(title="Trafik Olyckor", data=user_input)

        # Get the default latitude and longitude from Home Assistant config
        default_latitude = round(float(self.hass.config.latitude), 2)
        default_longitude = round(float(self.hass.config.longitude), 2)

        types = await fetch_types()
        types_list = [t[0] for t in types] if types else []
        types_list.append("Visa alla")

        activity_choices = {
            "show_only_active": "Visa endast aktiva händelser",
            "week_1": "Visa händelser från senaste veckan",
            "week_2": "Visa händelser från senaste 2 veckorna",
            "week_3": "Visa händelser från senaste 3 veckorna",
            "week_4": "Visa händelser från senaste 4 veckorna"
        }

        # Define the schema
        schema = vol.Schema({
            "latitude_info": "Ange latitud:",  # Lägg till en textsträng här
            vol.Required(CONF_LATITUDE, default=default_latitude): cv.string,
            "longitude_info": "Ange longitud:",  # Och här
            vol.Required(CONF_LONGITUDE, default=default_longitude): cv.string,
            "radius_info": "Ange radie (i km):",  # Och här
            vol.Required(CONF_RADIUS, default="40"): cv.positive_int,
            "type_info": "Välj typ av olycka:",  # Ändra även här
            vol.Required(CONF_TYPE, default="Visa alla"): vol.In(types_list),
            "activity_info": "Välj tidsperiod för händelser:",
            vol.Required("activity_option", default="show_only_active"): vol.In(activity_choices),
            "update_info": "Uppdateringsintervall (minuter):",
            vol.Required(CONF_SCAN_INTERVAL, default=5): vol.All(
                vol.Coerce(int), vol.Range(min=5, max=60)
            )
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
