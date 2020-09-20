# SmartLightGroup
This is platform is derived from the regular Home Assistant LightGroup and offers the same services just a bit smarter.

## When do you benefit from using it
- If you have different light types within the same group and would like to switch them smarter
- If you want to provide a default value when turning on

## What Problem does it solve
You have your regular white on/off light (maybe with a Shelly or a Sonof binary switch) and some colored Philips Hue lamp in your kitchen.
You switch the light to blue of your regular home assistant group kitchen (`group.kitchen`) and your Philips Hue lamps will light up blue, but your main light will be switched on as well.
This platform will not switch on your main kitchen light. However if you afterwards switch the color to white it will turn on your main kitchen light and also turn it back off when switching to blue again.
Also when turning your light to 10% it will not turn on your main light, but if you switch it to 90% it will.

## Configuration

All parameters except `name` and `entities` are optional. The optional parameters default to the values used below:
```
light:
  - platform: smart_light_group
    name: office
    entities:
      - light.officeceiling
      - light.officeshelf_hue
      - light.hue_iris
    default_brightness: 255
    default_color_temp: 360
    default_h: 50
    default_s: 40
    default_white_value: 255
    lower_bound_color_temperature_white_lights: 175
    upper_bound_color_temperature_white_lights: 450
    upper_bound_saturation_white_lights: 80.0
    lower_bound_brightness_non_dimmable_lights: 205 
    auto_adapt_white_value: True
    auto_convert_color_temperature_to_hs: True 
```