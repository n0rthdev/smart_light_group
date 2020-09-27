"""This platform allows several lights to be grouped into one light."""
import asyncio
import logging
from typing import Any, Callable, Iterator, List, Optional, Tuple, cast, Dict

import voluptuous as vol

from homeassistant.components import light
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_EFFECT_LIST,
    ATTR_FLASH,
    ATTR_HS_COLOR,
    ATTR_MAX_MIREDS,
    ATTR_MIN_MIREDS,
    ATTR_TRANSITION,
    ATTR_WHITE_VALUE,
    PLATFORM_SCHEMA,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    SUPPORT_EFFECT,
    SUPPORT_FLASH,
    SUPPORT_TRANSITION,
    SUPPORT_WHITE_VALUE,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    CONF_ENTITIES,
    CONF_NAME,
    STATE_ON,
    STATE_UNAVAILABLE,
)

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType, HomeAssistantType
from homeassistant.util import color as color_util

from homeassistant.components.group.light import LightGroup

# mypy: allow-incomplete-defs, allow-untyped-calls, allow-untyped-defs
# mypy: no-check-untyped-defs

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Smart Light Group"

DEFAULT_BRIGHTNESS = "default_brightness"
DEFAULT_COLOR_TEMP = "default_color_temp"
DEFAULT_H = "default_h"
DEFAULT_S = "default_s"
DEFAULT_WHITE_VALUE = "default_white_value"

LOWER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS = "lower_bound_color_temperature_white_lights"
UPPER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS = "upper_bound_color_temperature_white_lights"
UPPER_BOUND_SATURATION_WHITE_LIGHTS = "upper_bound_saturation_white_lights"
LOWER_BOUND_BRIGHTNESS_NON_DIMMABLE_LIGHTS = "lower_bound_brightness_non_dimmable_lights"
AUTO_ADAPT_WHITE_VALUE = "auto_adapt_white_value"
AUTO_CONVERT_COLOR_TEMPERATURE_TO_HS = "auto_convert_color_temperature_to_hs"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_ENTITIES): cv.entities_domain(light.DOMAIN),

        vol.Optional(DEFAULT_BRIGHTNESS, default=255): cv.positive_int,
        vol.Optional(DEFAULT_COLOR_TEMP, default=320): cv.positive_int,
        vol.Optional(DEFAULT_H, default=50): cv.positive_int,
        vol.Optional(DEFAULT_S, default=40): cv.positive_int,
        vol.Optional(DEFAULT_WHITE_VALUE, default=255): cv.positive_int,

        vol.Optional(LOWER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS, default=175): cv.positive_int,
        vol.Optional(UPPER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS, default=450): cv.positive_int,
        vol.Optional(UPPER_BOUND_SATURATION_WHITE_LIGHTS, default=80.0): vol.All(vol.Coerce(float),
                                                                                 vol.Range(min=0, max=255)),
        vol.Optional(LOWER_BOUND_BRIGHTNESS_NON_DIMMABLE_LIGHTS, default=205): cv.positive_int,
        vol.Optional(AUTO_ADAPT_WHITE_VALUE, default=True): vol.Coerce(bool),
        vol.Optional(AUTO_CONVERT_COLOR_TEMPERATURE_TO_HS, default=True): vol.Coerce(bool),
    }
)

SUPPORT_GROUP_LIGHT = (
        SUPPORT_BRIGHTNESS
        | SUPPORT_COLOR_TEMP
        | SUPPORT_EFFECT
        | SUPPORT_FLASH
        | SUPPORT_COLOR
        | SUPPORT_TRANSITION
        | SUPPORT_WHITE_VALUE
)


async def async_setup_platform(
        hass: HomeAssistantType, config: ConfigType, async_add_entities, discovery_info=None
) -> None:
    """Initialize light.group platform."""
    async_add_entities(
        [SmartLightGroup(cast(str, config.get(CONF_NAME)), config[CONF_ENTITIES], config)]
    )


class SmartLightGroup(LightGroup):
    """Representation of a light group."""

    def __init__(self, name: str, entity_ids: List[str], conf: Dict[str, Any]) -> None:
        """Initialize a light group."""
        self._name = name
        self._entity_ids = entity_ids
        self._is_on = False
        self._available = False
        self._brightness: Optional[int] = None
        self._hs_color: Optional[Tuple[float, float]] = None
        self._color_temp: Optional[int] = None
        self._min_mireds: Optional[int] = 154
        self._max_mireds: Optional[int] = 500
        self._white_value: Optional[int] = None
        self._effect_list: Optional[List[str]] = None
        self._effect: Optional[str] = None
        self._supported_features: int = 0

        self._default_brightness: int = conf.get(DEFAULT_BRIGHTNESS)
        self._default_color_temp: int = conf.get(DEFAULT_COLOR_TEMP)
        self._default_h: float = conf.get(DEFAULT_H) * 1.0
        self._default_s: float = conf.get(DEFAULT_S) * 1.0
        self._default_white_value: int = conf.get(DEFAULT_WHITE_VALUE)

        self._auto_convert_temp_to_hs: bool = conf.get(AUTO_CONVERT_COLOR_TEMPERATURE_TO_HS)
        self._auto_adapt_white_value: bool = conf.get(AUTO_ADAPT_WHITE_VALUE)
        self._threshold_lower_temperature_white_lights: int = conf.get(LOWER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS)
        self._threshold_upper_temperature_white_lights: int = conf.get(UPPER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS)
        self._threshold_upper_saturation_white_lights: float = conf.get(UPPER_BOUND_SATURATION_WHITE_LIGHTS)
        self._threshold_lower_brightness_non_dimmable_lights: int = conf.get(LOWER_BOUND_BRIGHTNESS_NON_DIMMABLE_LIGHTS)
        self._empty_turn_on_is_reset_to_default: bool = True
        self._color_temp_before_hs_color: bool = True

    def _non_dimmable_on_by_temperature(self, brightness: int, temperature: int) -> bool:
        return (brightness > self._threshold_lower_brightness_non_dimmable_lights) and (
                self._threshold_lower_temperature_white_lights <= temperature and temperature <= self._threshold_upper_temperature_white_lights)

    def _non_dimmable_on_by_saturation(self, brightness: int, saturation: float) -> bool:
        return (brightness > self._threshold_lower_brightness_non_dimmable_lights) and (
                saturation < self._threshold_upper_saturation_white_lights)

    def _brightness_for_dimmable_by_temperature(self, brightness: int, temperature: int) -> int:
        return brightness if (
                self._threshold_lower_temperature_white_lights <= temperature and temperature <= self._threshold_upper_temperature_white_lights) else 0

    def _brightness_for_dimmable_by_saturation(self, brightness: int, saturation: float) -> int:
        return brightness if (saturation < self._threshold_upper_saturation_white_lights) else 0

    def _brightness_for_temperature(self, brightness: int, saturation: float) -> int:
        return brightness if (saturation < self._threshold_upper_saturation_white_lights) else 0

    def _hs_color_for_temperature(self, temperature: int) -> Tuple[float, float]:
        temp_k = color_util.color_temperature_mired_to_kelvin(temperature)
        hs_color = color_util.color_temperature_to_hs(temp_k)
        return hs_color

    def _calculate_white_value(self, hs_color: Tuple[float, float], brightness: int) -> int:
        if hs_color[1] < self._threshold_upper_saturation_white_lights:
            rgb = color_util.color_hsv_to_RGB(hs_color[0], hs_color[1], brightness / 255 * 100)
            return (int)(min(rgb) * (brightness / 255.0))
        else:
            return 0

    async def async_turn_on(self, **kwargs):
        """Forward the turn_on command to all lights in the light group."""
        was_off = not self._is_on

        temperature_and_color_entity_ids = []
        color_and_white_entity_ids = []
        color_entity_ids = []
        temperature_entity_ids = []
        dimmable_entity_ids = []
        non_dimmable_entity_ids = []

        for entity_id in self._entity_ids:
            state = self.hass.states.get(entity_id)
            if not state:
                continue
            support = state.attributes.get(ATTR_SUPPORTED_FEATURES)

            sup_bri = bool(support & SUPPORT_BRIGHTNESS)
            sup_col = bool(support & SUPPORT_COLOR)
            sup_white_value = bool(support & SUPPORT_WHITE_VALUE)
            sup_temp = bool(support & SUPPORT_COLOR_TEMP)

            if sup_bri and sup_col and sup_temp:
                temperature_and_color_entity_ids.append(entity_id)  # hue color
            elif sup_bri and sup_col and sup_white_value:
                color_and_white_entity_ids.append(entity_id)  # rgbw strips
            elif sup_bri and sup_col:
                color_entity_ids.append(entity_id)  # rgb strips
            elif sup_bri and sup_temp:
                temperature_entity_ids.append(entity_id)  # hue ambiance white
            elif sup_bri:
                dimmable_entity_ids.append(entity_id)  # hue white
            else:
                non_dimmable_entity_ids.append(entity_id)  # regular white on/off light

        _LOGGER.debug(self._name + ": " +
                      "Entities: temperature_and_color: " + str(temperature_and_color_entity_ids) +
                      ", color_and_white: " + str(color_and_white_entity_ids) +
                      ", color: " + str(color_entity_ids) +
                      ", temperature: " + str(temperature_entity_ids) +
                      ", dimmable: " + str(dimmable_entity_ids) +
                      ", non_dimmable: " + str(non_dimmable_entity_ids))

        old_brightness = self._brightness
        old_color_temp = self._color_temp
        old_hs_color = self._hs_color
        old_white_value = self._white_value

        _LOGGER.debug(self._name + ": " + "Old Values:"
                                          " old_on: " + str(not was_off) +
                      ", old_brightness: " + str(old_brightness) +
                      ", old_color_temp: " + str(old_color_temp) +
                      ", old_hs_color: " + str(old_hs_color) +
                      ", old_white_value: " + str(old_white_value))

        # old_non_dimmable_on = self._non_dimmable_on(old_brightness, old_hs_color[1])
        # old_brightness_temperature = self._brightness_for_temperature(old_brightness, old_hs_color[1])
        # old_emulated_temperature_as_hs_color = self._hs_color_for_temperature(old_color_temp)
        # old_emulated_white_value = self._calculate_white_value(old_hs_color)

        supplied_brightness = ATTR_BRIGHTNESS in kwargs
        supplied_color_temp = ATTR_COLOR_TEMP in kwargs
        supplied_hs_color = ATTR_HS_COLOR in kwargs
        supplied_white_value = ATTR_WHITE_VALUE in kwargs

        no_light_attr_supplied = not supplied_brightness and not supplied_color_temp and not supplied_hs_color and not supplied_white_value
        is_reset_to_default = (self._empty_turn_on_is_reset_to_default or was_off) and no_light_attr_supplied
        allow_using_old_values = not is_reset_to_default

        new_brightness = self._default_brightness
        using_old_brightness = False
        if supplied_brightness:
            new_brightness = kwargs[ATTR_BRIGHTNESS]
        elif old_brightness is not None and allow_using_old_values:
            new_brightness = old_brightness
            using_old_brightness = True

        new_color_temp = self._default_color_temp
        using_old_color_temp = False
        if supplied_color_temp:
            new_color_temp = kwargs[ATTR_COLOR_TEMP]
        elif old_color_temp is not None and allow_using_old_values:
            new_color_temp = old_color_temp
            using_old_color_temp = True

        new_hs_color = (self._default_h, self._default_s)
        using_old_hs_color = False
        if supplied_hs_color:
            new_hs_color = kwargs[ATTR_HS_COLOR]
        elif old_hs_color is not None and allow_using_old_values:
            new_hs_color = old_hs_color
            using_old_hs_color = True

        new_white_value = self._default_white_value
        using_old_white_value = False
        if supplied_white_value:
            new_white_value = kwargs[ATTR_WHITE_VALUE]
        elif old_white_value is not None and allow_using_old_values:
            new_white_value = old_white_value
            using_old_white_value = True


        _LOGGER.debug(self._name + " after value updates: " + "Kwargs " + str(kwargs) +
                      ", supplied_brightness: " + str(supplied_brightness) +
                      ", supplied_color_temp: " + str(supplied_color_temp) +
                      ", supplied_hs_color: " + str(supplied_hs_color) +
                      ", supplied_white_value: " + str(supplied_white_value))

        _LOGGER.debug(self._name + " after value updates: " + "New Values: " +
                      ", new_brightness: " + str(new_brightness) +
                      ", new_color_temp: " + str(new_color_temp) +
                      ", new_hs_color: " + str(new_hs_color) +
                      ", new_white_value: " + str(new_white_value))

        apply_all_attributes = was_off or is_reset_to_default

        apply_brightness = supplied_brightness or apply_all_attributes

        apply_color_temp = supplied_color_temp or apply_all_attributes

        # Adapt HS color if color temp has a more recent value, and auto convert is enabled
        color_temp_has_newer_value_than_hs_color = not supplied_hs_color and (
                    supplied_color_temp or (using_old_color_temp and not using_old_hs_color))
        do_convert_temp_to_hs = self._auto_convert_temp_to_hs and not is_reset_to_default and color_temp_has_newer_value_than_hs_color
        if do_convert_temp_to_hs:
            new_hs_color = self._hs_color_for_temperature(new_color_temp)
            supplied_hs_color = True
        apply_hs_color = supplied_hs_color or do_convert_temp_to_hs or apply_all_attributes

        # Adapt white_value if other values have a more recent value, and auto adapt is enabled
        other_attributes_have_supplied_value = supplied_hs_color or supplied_color_temp or supplied_brightness
        other_attributes_use_old_values = using_old_hs_color or using_old_color_temp or using_old_brightness
        other_attributes_have_newer_values_than_white_value = not supplied_white_value and (other_attributes_have_supplied_value or (using_old_white_value and not other_attributes_use_old_values))
        do_adapt_white_value = self._auto_adapt_white_value and not is_reset_to_default and other_attributes_have_newer_values_than_white_value
        if do_adapt_white_value:
            new_white_value = self._calculate_white_value(new_hs_color, new_brightness)
        apply_white_value = supplied_white_value or do_adapt_white_value or apply_all_attributes

        # Determine which source to use for configuring dimmable and non dimmable lights
        hs_color_has_newer_value_than_color_temp = not supplied_color_temp and (
                supplied_hs_color or (using_old_hs_color and not using_old_color_temp))
    
        if hs_color_has_newer_value_than_color_temp:
            # Only if HS is given and no color temp is given use HS to determine settings for non_dimmable, dimmable
            new_non_dimmable_on = self._non_dimmable_on_by_saturation(new_brightness, new_hs_color[1])
            new_brightness_for_dimmable = self._brightness_for_dimmable_by_saturation(new_brightness, new_hs_color[1])
            # if only HS specified, temperature lights might be dimmed, or even switched off completely
            new_brightness_for_temperature = self._brightness_for_temperature(new_brightness, new_hs_color[1])
        else:
            # If color temp given use it to determine settings for non_dimmable, dimmable
            new_non_dimmable_on = self._non_dimmable_on_by_temperature(new_brightness, new_color_temp)
            new_brightness_for_dimmable = self._brightness_for_dimmable_by_temperature(new_brightness, new_color_temp)
            # if color temp specified, temperature lights may use regular brightness
            new_brightness_for_temperature = new_brightness

        use_color_temp_for_temperature_and_color_entities = not hs_color_has_newer_value_than_color_temp and self._color_temp_before_hs_color

        _LOGGER.debug(self._name + " adaptions: " +
                      "no_light_attr_supplied: " + str(no_light_attr_supplied) +
                      ", is_reset_to_default: " + str(is_reset_to_default) +
                      ", do_convert_temp_to_hs: " + str(do_convert_temp_to_hs) +
                      ", color_temp_has_newer_value_than_hs_color: " + str(color_temp_has_newer_value_than_hs_color) +
                      ", hs_color_has_newer_value_than_color_temp: " + str(hs_color_has_newer_value_than_color_temp) +
                      ", use_color_temp_for_temperature_and_color_entities: " + str(use_color_temp_for_temperature_and_color_entities) +
                      ", do_adapt_white_value: " + str(do_adapt_white_value))

        _LOGGER.debug(self._name + " after auto value adaptions: " + "Kwargs " + str(kwargs) +
                      ", apply_brightness: " + str(apply_brightness) +
                      ", apply_color_temp: " + str(apply_color_temp) +
                      ", apply_hs_color: " + str(apply_hs_color) +
                      ", apply_white_value: " + str(apply_white_value))

        _LOGGER.info(self._name + ": " + "New Values Final: " +
                      "new_brightness: " + str(new_brightness) +
                      ", new_color_temp: " + str(new_color_temp) +
                      ", new_hs_color: " + str(new_hs_color) +
                      ", new_white_value: " + str(new_white_value) +
                      ", new_non_dimmable_on: " + str(new_non_dimmable_on) +
                      ", new_brightness_for_dimmable: " + str(new_brightness_for_dimmable) +
                      ", new_brightness_for_temperature: " + str(new_brightness_for_temperature) +
                      ", use_color_temp_for_temperature_and_color_entities: " + str(use_color_temp_for_temperature_and_color_entities))

        commands = []

        if non_dimmable_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = non_dimmable_entity_ids

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON if new_non_dimmable_on else light.SERVICE_TURN_OFF,
                    data,
                    blocking=True,
                    context=self._context,
                )
            )

        if dimmable_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = dimmable_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness_for_dimmable

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data,
                    blocking=True,
                    context=self._context,
                )
            )

        if temperature_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = temperature_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness_for_temperature
            data[ATTR_COLOR_TEMP] = new_color_temp

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data,
                    blocking=True,
                    context=self._context,
                )
            )

        if color_and_white_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = color_and_white_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness
            data[ATTR_HS_COLOR] = new_hs_color
            data[ATTR_WHITE_VALUE] = new_white_value

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data,
                    blocking=True,
                    context=self._context,
                )
            )

        if color_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = color_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness
            data[ATTR_HS_COLOR] = new_hs_color

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data,
                    blocking=True,
                    context=self._context,
                )
            )

        if temperature_and_color_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = temperature_and_color_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness
            if use_color_temp_for_temperature_and_color_entities:
                data[ATTR_COLOR_TEMP] = new_color_temp
            else:
                data[ATTR_HS_COLOR] = new_hs_color

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data,
                    blocking=True,
                    context=self._context,
                )
            )

        if commands:
            await asyncio.gather(*commands)
