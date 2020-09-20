"""This platform allows several lights to be grouped into one light."""
import asyncio
from collections import Counter
import itertools
import logging
from typing import Any, Callable, Iterator, List, Optional, Tuple, cast

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
from homeassistant.core import State
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType, HomeAssistantType
from homeassistant.util import color as color_util

from homeassistant.components.group import GroupEntity

# from homeassistant.components.group.light import LightGroup

# mypy: allow-incomplete-defs, allow-untyped-calls, allow-untyped-defs
# mypy: no-check-untyped-defs

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Smart Light Group"

LOWER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS = "lower_bound_color_temperature_white_lights"
UPPER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS = "upper_bound_color_temperature_white_lights"
UPPER_BOUND_SATURATION_WHITE_LIGHTS = "upper_bound_saturation_white_lights"
LOWER_BOUND_BRIGHTNESS_NON_DIMMABLE_LIGHTS = "lower_bound_brightness_non_dimmable_lights"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Required(CONF_ENTITIES): cv.entities_domain(light.DOMAIN),
        vol.Optional(LOWER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS, default=175): cv.positive_int,
        vol.Optional(UPPER_BOUND_COLOR_TEMPERATURE_WHITE_LIGHTS, default=450): cv.positive_int,
        vol.Optional(UPPER_BOUND_SATURATION_WHITE_LIGHTS, default=55.0): vol.All(vol.Coerce(float),
                                                                                 vol.Range(min=0, max=255)),
        vol.Optional(LOWER_BOUND_BRIGHTNESS_NON_DIMMABLE_LIGHTS, default=205): cv.positive_int,
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
        [SmartLightGroup(cast(str, config.get(CONF_NAME)), config[CONF_ENTITIES])]
    )


class SmartLightGroup(GroupEntity, light.LightEntity):
    """Representation of a light group."""

    def __init__(self, name: str, entity_ids: List[str]) -> None:
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

        self._default_brightness: int = 255
        self._default_h: float = 50.0
        self._default_s: float = 40.0
        self._default_color_temp: int = 320
        self._default_whitevalue: int = 255

        self._auto_convert_temp_to_hs: bool = True
        self._auto_adapt_white_value: bool = True
        self._threshold_lower_temperature_white_lights = 175
        self._threshold_upper_temperature_white_lights = 450
        self._threshold_upper_saturation_white_lights = 55
        self._threshold_lower_brightness_non_dimmable_lights = 205

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""

        async def async_state_changed_listener(event):
            """Handle child updates."""
            self.async_set_context(event.context)
            await self.async_defer_or_update_ha_state()

        assert self.hass
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, self._entity_ids, async_state_changed_listener
            )
        )
        await super().async_added_to_hass()

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def is_on(self) -> bool:
        """Return the on/off state of the light group."""
        return self._is_on

    @property
    def available(self) -> bool:
        """Return whether the light group is available."""
        return self._available

    @property
    def brightness(self) -> Optional[int]:
        """Return the brightness of this light group between 0..255."""
        return self._brightness

    @property
    def hs_color(self) -> Optional[Tuple[float, float]]:
        """Return the HS color value [float, float]."""
        return self._hs_color

    @property
    def color_temp(self) -> Optional[int]:
        """Return the CT color value in mireds."""
        return self._color_temp

    @property
    def min_mireds(self) -> Optional[int]:
        """Return the coldest color_temp that this light group supports."""
        return self._min_mireds

    @property
    def max_mireds(self) -> Optional[int]:
        """Return the warmest color_temp that this light group supports."""
        return self._max_mireds

    @property
    def white_value(self) -> Optional[int]:
        """Return the white value of this light group between 0..255."""
        return self._white_value

    @property
    def effect_list(self) -> Optional[List[str]]:
        """Return the list of supported effects."""
        return self._effect_list

    @property
    def effect(self) -> Optional[str]:
        """Return the current effect."""
        return self._effect

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return self._supported_features

    @property
    def should_poll(self) -> bool:
        """No polling needed for a light group."""
        return False

    @property
    def device_state_attributes(self):
        """Return the state attributes for the light group."""
        return {ATTR_ENTITY_ID: self._entity_ids}

    def _non_dimmable_on(self, brightness: int, saturation: float) -> bool:
        return (brightness > self._threshold_lower_brightness_non_dimmable_lights) and (
                saturation < self._threshold_upper_saturation_white_lights)

    def _brightness_for_dimmable(self, brightness: int, saturation: float) -> int:
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
            return min(rgb) * brightness
        else:
            return 0

    async def async_turn_on(self, **kwargs):
        """Forward the turn_on command to all lights in the light group."""
        is_off = not self._is_on

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
                non_dimmable_entity_ids.append(entity_id)  # regular white on/of light

        _LOGGER.warn(
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


        _LOGGER.warn("Old Values: "
                     ", old_brightness: " + str(old_brightness) +
                     ", old_color_temp: " + str(old_color_temp) +
                     ", old_hs_color: " + str(old_hs_color) +
                     ", old_white_value: " + str(old_white_value))

        # old_non_dimmable_on = self._non_dimmable_on(old_brightness, old_hs_color[1])
        # old_brightness_temperature = self._brightness_for_temperature(old_brightness, old_hs_color[1])
        # old_emulated_temperature_as_hs_color = self._hs_color_for_temperature(old_color_temp)
        # old_emulated_white_value = self._calculate_white_value(old_hs_color)

        if ATTR_BRIGHTNESS in kwargs:
            new_brightness = kwargs[ATTR_BRIGHTNESS]
            apply_brightness = True
        elif is_off or old_brightness is None:
            new_brightness = self._default_brightness
            apply_brightness = is_off
        else:
            new_brightness = old_brightness
            apply_brightness = False

        if ATTR_COLOR_TEMP in kwargs:
            new_color_temp = kwargs[ATTR_COLOR_TEMP]
            apply_color_temp = True
        elif is_off or old_color_temp is None:
            new_color_temp = self._default_color_temp
            apply_color_temp = is_off
        else:
            new_color_temp = old_color_temp
            apply_color_temp = False

        if ATTR_HS_COLOR in kwargs:
            new_hs_color = kwargs[ATTR_HS_COLOR]
            apply_hs_color = True
        elif is_off or old_hs_color is None:
            new_hs_color = (self._default_h, self._default_s)
            apply_hs_color = is_off
        else:
            new_hs_color = old_hs_color
            apply_hs_color = False

        if ATTR_WHITE_VALUE in kwargs:
            new_white_value = kwargs[ATTR_WHITE_VALUE]
            apply_white_value = True
        elif is_off or old_white_value is None:
            new_white_value = self._default_whitevalue
            apply_white_value = is_off
        else:
            new_white_value = old_white_value
            apply_white_value = False

        _LOGGER.warn("Kwargs " + str(kwargs) +
                     ", apply_brightness: " + str(apply_brightness) +
                     ", apply_color_temp: " + str(apply_color_temp) +
                     ", apply_hs_color: " + str(apply_hs_color) +
                     ", apply_white_value: " + str(apply_white_value))
        _LOGGER.warn("New Values: "
                     ", new_brightness: " + str(new_brightness) +
                     ", new_color_temp: " + str(new_color_temp) +
                     ", new_hs_color: " + str(new_hs_color) +
                     ", new_white_value: " + str(new_white_value))

        if self._auto_convert_temp_to_hs and apply_color_temp and not apply_hs_color:
            new_hs_color = self._hs_color_for_temperature(new_color_temp)
            apply_hs_color = True

        new_non_dimmable_on = self._non_dimmable_on(new_brightness, new_hs_color[1])

        new_brightness_for_dimmable = self._brightness_for_dimmable(new_brightness, new_hs_color[1])

        if not apply_color_temp and apply_hs_color:
            new_brightness_for_temperature = self._brightness_for_temperature(new_brightness, new_hs_color[1])
        else:
            new_brightness_for_temperature = new_brightness

        if self._auto_convert_temp_to_hs and not apply_white_value and (
                apply_hs_color or apply_color_temp or apply_brightness):
            new_white_value = self._calculate_white_value(new_hs_color, new_brightness)

        _LOGGER.warn("New Values Final: "
                     ", new_brightness: " + str(new_brightness) +
                     ", new_color_temp: " + str(new_color_temp) +
                     ", new_hs_color: " + str(new_hs_color) +
                     ", new_white_value: " + str(new_white_value) +
                     ", new_non_dimmable_on: " + str(new_non_dimmable_on) +
                     ", new_brightness_for_dimmable: " + str(new_brightness_for_dimmable) +
                     ", new_brightness_for_temperature: " + str(new_brightness_for_temperature))


        commands = []

        if non_dimmable_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = non_dimmable_entity_ids

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON if new_non_dimmable_on else light.SERVICE_TURN_OFF,
                    data.copy(),
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
                    data.copy(),
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
                    data.copy(),
                    blocking=True,
                    context=self._context,
                )
            )
        if color_and_white_entity_ids + color_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = color_and_white_entity_ids + color_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness
            data[ATTR_HS_COLOR] = new_hs_color
            data[ATTR_WHITE_VALUE] = new_white_value

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data.copy(),
                    blocking=True,
                    context=self._context,
                )
            )

        if temperature_and_color_entity_ids:
            data = {}
            data[ATTR_ENTITY_ID] = temperature_and_color_entity_ids
            data[ATTR_BRIGHTNESS] = new_brightness
            if apply_hs_color and not apply_color_temp:
                data[ATTR_HS_COLOR] = new_hs_color
            else:
                data[ATTR_COLOR_TEMP] = new_color_temp

            commands.append(
                self.hass.services.async_call(
                    light.DOMAIN,
                    light.SERVICE_TURN_ON,
                    data.copy(),
                    blocking=True,
                    context=self._context,
                )
            )

        if commands:
            await asyncio.gather(*commands)

    async def async_turn_off(self, **kwargs):
        """Forward the turn_off command to all lights in the light group."""
        data = {ATTR_ENTITY_ID: self._entity_ids}

        if ATTR_TRANSITION in kwargs:
            data[ATTR_TRANSITION] = kwargs[ATTR_TRANSITION]

        await self.hass.services.async_call(
            light.DOMAIN,
            light.SERVICE_TURN_OFF,
            data,
            blocking=True,
            context=self._context,
        )

    async def async_update(self):
        """Query all members and determine the light group state."""
        all_states = [self.hass.states.get(x) for x in self._entity_ids]
        states: List[State] = list(filter(None, all_states))
        on_states = [state for state in states if state.state == STATE_ON]

        self._is_on = len(on_states) > 0
        self._available = any(state.state != STATE_UNAVAILABLE for state in states)

        self._brightness = _reduce_attribute(on_states, ATTR_BRIGHTNESS)

        self._hs_color = _reduce_attribute(on_states, ATTR_HS_COLOR, reduce=_mean_tuple)

        self._white_value = _reduce_attribute(on_states, ATTR_WHITE_VALUE)

        self._color_temp = _reduce_attribute(on_states, ATTR_COLOR_TEMP)
        self._min_mireds = _reduce_attribute(
            states, ATTR_MIN_MIREDS, default=154, reduce=min
        )
        self._max_mireds = _reduce_attribute(
            states, ATTR_MAX_MIREDS, default=500, reduce=max
        )

        self._effect_list = None
        all_effect_lists = list(_find_state_attributes(states, ATTR_EFFECT_LIST))
        if all_effect_lists:
            # Merge all effects from all effect_lists with a union merge.
            self._effect_list = list(set().union(*all_effect_lists))

        self._effect = None
        all_effects = list(_find_state_attributes(on_states, ATTR_EFFECT))
        if all_effects:
            # Report the most common effect.
            effects_count = Counter(itertools.chain(all_effects))
            self._effect = effects_count.most_common(1)[0][0]

        self._supported_features = 0
        for support in _find_state_attributes(states, ATTR_SUPPORTED_FEATURES):
            # Merge supported features by emulating support for every feature
            # we find.
            self._supported_features |= support
        # Bitwise-and the supported features with the GroupedLight's features
        # so that we don't break in the future when a new feature is added.
        self._supported_features &= SUPPORT_GROUP_LIGHT


def _find_state_attributes(states: List[State], key: str) -> Iterator[Any]:
    """Find attributes with matching key from states."""
    for state in states:
        value = state.attributes.get(key)
        if value is not None:
            yield value


def _mean_int(*args):
    """Return the mean of the supplied values."""
    return int(sum(args) / len(args))


def _mean_tuple(*args):
    """Return the mean values along the columns of the supplied values."""
    return tuple(sum(x) / len(x) for x in zip(*args))


def _reduce_attribute(
        states: List[State],
        key: str,
        default: Optional[Any] = None,
        reduce: Callable[..., Any] = _mean_int,
) -> Any:
    """Find the first attribute matching key from states.
    If none are found, return default.
    """
    attrs = list(_find_state_attributes(states, key))

    if not attrs:
        return default

    if len(attrs) == 1:
        return attrs[0]

    return reduce(*attrs)
