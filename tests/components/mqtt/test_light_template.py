"""The tests for the MQTT Template light platform.

Configuration example with all features:

mqtt:
    light:
        schema: template
        name: mqtt_template_light_1
        state_topic: 'home/rgb1'
        command_topic: 'home/rgb1/set'
        command_on_template: >
            on,{{ brightness|d }},{{ red|d }}-{{ green|d }}-{{ blue|d }}
        command_off_template: 'off'
        state_template: '{{ value.split(",")[0] }}'
        brightness_template: '{{ value.split(",")[1] }}'
        color_temp_template: '{{ value.split(",")[2] }}'
        red_template: '{{ value.split(",")[4].split("-")[0] }}'
        green_template: '{{ value.split(",")[4].split("-")[1] }}'
        blue_template: '{{ value.split(",")[4].split("-")[2] }}'

If your light doesn't support brightness feature, omit `brightness_template`.

If your light doesn't support color temp feature, omit `color_temp_template`.

If your light doesn't support RGB feature, omit `(red|green|blue)_template`.
"""
import copy
from unittest.mock import patch

import pytest

from homeassistant.components import light, mqtt
from homeassistant.components.mqtt.light.schema_basic import (
    MQTT_LIGHT_ATTRIBUTES_BLOCKED,
)
from homeassistant.const import (
    ATTR_ASSUMED_STATE,
    ATTR_SUPPORTED_FEATURES,
    STATE_OFF,
    STATE_ON,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.setup import async_setup_component

from .test_common import (
    help_test_availability_when_connection_lost,
    help_test_availability_without_topic,
    help_test_custom_availability_payload,
    help_test_default_availability_payload,
    help_test_discovery_broken,
    help_test_discovery_removal,
    help_test_discovery_update,
    help_test_discovery_update_attr,
    help_test_discovery_update_unchanged,
    help_test_encoding_subscribable_topics,
    help_test_entity_debug_info_message,
    help_test_entity_device_info_remove,
    help_test_entity_device_info_update,
    help_test_entity_device_info_with_connection,
    help_test_entity_device_info_with_identifier,
    help_test_entity_id_update_discovery_update,
    help_test_entity_id_update_subscriptions,
    help_test_publishing_with_custom_encoding,
    help_test_reloadable,
    help_test_setting_attribute_via_mqtt_json_message,
    help_test_setting_attribute_with_template,
    help_test_setting_blocked_attribute_via_mqtt_json_message,
    help_test_setup_manual_entity_from_yaml,
    help_test_unique_id,
    help_test_unload_config_entry_with_platform,
    help_test_update_with_json_attrs_bad_json,
    help_test_update_with_json_attrs_not_dict,
)

from tests.common import async_fire_mqtt_message, mock_restore_cache
from tests.components.light import common

DEFAULT_CONFIG = {
    mqtt.DOMAIN: {
        light.DOMAIN: {
            "schema": "template",
            "name": "test",
            "command_topic": "test-topic",
            "command_on_template": "on,{{ transition }}",
            "command_off_template": "off,{{ transition|d }}",
        }
    }
}


@pytest.fixture(autouse=True)
def light_platform_only():
    """Only setup the light platform to speed up tests."""
    with patch("homeassistant.components.mqtt.PLATFORMS", [Platform.LIGHT]):
        yield


@pytest.mark.parametrize(
    "test_config",
    [
        ({"schema": "template", "name": "test"},),
        (
            {
                "schema": "template",
                "name": "test",
                "command_topic": "test_topic",
            },
        ),
        (
            {
                "schema": "template",
                "name": "test",
                "command_topic": "test_topic",
                "command_on_template": "on",
            },
        ),
        (
            {
                "schema": "template",
                "name": "test",
                "command_topic": "test_topic",
                "command_off_template": "off",
            },
        ),
    ],
)
async def test_setup_fails(hass: HomeAssistant, caplog, test_config) -> None:
    """Test that setup fails with missing required configuration items."""
    assert not await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {mqtt.DOMAIN: {light.DOMAIN: test_config}},
    )
    assert "Invalid config for [mqtt]" in caplog.text


async def test_rgb_light(hass: HomeAssistant, mqtt_mock_entry_with_yaml_config) -> None:
    """Test RGB light flags brightness support."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on",
                    "command_off_template": "off",
                    "red_template": '{{ value.split(",")[4].' 'split("-")[0] }}',
                    "green_template": '{{ value.split(",")[4].' 'split("-")[1] }}',
                    "blue_template": '{{ value.split(",")[4].' 'split("-")[2] }}',
                }
            }
        },
    )
    await hass.async_block_till_done()
    await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    color_modes = [light.ColorMode.HS]
    assert state.attributes.get(light.ATTR_SUPPORTED_COLOR_MODES) == color_modes
    expected_features = light.SUPPORT_FLASH | light.SUPPORT_TRANSITION
    assert state.attributes.get(ATTR_SUPPORTED_FEATURES) == expected_features


async def test_state_change_via_topic(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test state change via topic."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "state_topic": "test_light_rgb",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,"
                    "{{ brightness|d }},"
                    "{{ color_temp|d }},"
                    "{{ red|d }}-"
                    "{{ green|d }}-"
                    "{{ blue|d }}",
                    "command_off_template": "off",
                    "state_template": '{{ value.split(",")[0] }}',
                }
            }
        },
    )
    await hass.async_block_till_done()
    await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get("rgb_color") is None
    assert state.attributes.get("brightness") is None
    assert state.attributes.get("color_temp") is None
    assert not state.attributes.get(ATTR_ASSUMED_STATE)

    async_fire_mqtt_message(hass, "test_light_rgb", "on")

    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") is None
    assert state.attributes.get("brightness") is None
    assert state.attributes.get("color_temp") is None

    async_fire_mqtt_message(hass, "test_light_rgb", "off")

    state = hass.states.get("light.test")
    assert state.state == STATE_OFF

    async_fire_mqtt_message(hass, "test_light_rgb", "None")

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN


async def test_state_brightness_color_effect_temp_change_via_topic(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test state, bri, color, effect, color temp change."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "effect_list": ["rainbow", "colorloop"],
                    "state_topic": "test_light_rgb",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,"
                    "{{ brightness|d }},"
                    "{{ color_temp|d }},"
                    "{{ red|d }}-"
                    "{{ green|d }}-"
                    "{{ blue|d }},"
                    "{{ effect|d }}",
                    "command_off_template": "off",
                    "state_template": '{{ value.split(",")[0] }}',
                    "brightness_template": '{{ value.split(",")[1] }}',
                    "color_temp_template": '{{ value.split(",")[2] }}',
                    "red_template": '{{ value.split(",")[3].' 'split("-")[0] }}',
                    "green_template": '{{ value.split(",")[3].' 'split("-")[1] }}',
                    "blue_template": '{{ value.split(",")[3].' 'split("-")[2] }}',
                    "effect_template": '{{ value.split(",")[4] }}',
                }
            }
        },
    )
    await hass.async_block_till_done()
    await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get("rgb_color") is None
    assert state.attributes.get("brightness") is None
    assert state.attributes.get("effect") is None
    assert state.attributes.get("color_temp") is None
    assert not state.attributes.get(ATTR_ASSUMED_STATE)

    # turn on the light
    async_fire_mqtt_message(hass, "test_light_rgb", "on,255,145,255-128-64,")

    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") == (255, 128, 63)
    assert state.attributes.get("brightness") == 255
    assert state.attributes.get("color_temp") is None  # rgb color has priority
    assert state.attributes.get("effect") is None

    # turn on the light
    async_fire_mqtt_message(hass, "test_light_rgb", "on,255,145,None-None-None,")

    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") == (
        246,
        244,
        255,
    )  # temp converted to color
    assert state.attributes.get("brightness") == 255
    assert state.attributes.get("color_temp") == 145
    assert state.attributes.get("effect") is None
    assert state.attributes.get("xy_color") == (0.317, 0.317)  # temp converted to color
    assert state.attributes.get("hs_color") == (
        251.249,
        4.253,
    )  # temp converted to color

    # make the light state unknown
    async_fire_mqtt_message(hass, "test_light_rgb", "None")

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN

    # turn the light off
    async_fire_mqtt_message(hass, "test_light_rgb", "off")

    state = hass.states.get("light.test")
    assert state.state == STATE_OFF

    # lower the brightness
    async_fire_mqtt_message(hass, "test_light_rgb", "on,100")

    light_state = hass.states.get("light.test")
    assert light_state.attributes["brightness"] == 100

    # change the color temp
    async_fire_mqtt_message(hass, "test_light_rgb", "on,,195")

    light_state = hass.states.get("light.test")
    assert light_state.attributes["color_temp"] == 195

    # change the color
    async_fire_mqtt_message(hass, "test_light_rgb", "on,,,41-42-43")

    light_state = hass.states.get("light.test")
    assert light_state.attributes.get("rgb_color") == (243, 249, 255)

    # change the effect
    async_fire_mqtt_message(hass, "test_light_rgb", "on,,,41-42-43,rainbow")

    light_state = hass.states.get("light.test")
    assert light_state.attributes.get("effect") == "rainbow"


async def test_sending_mqtt_commands_and_optimistic(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test the sending of command in optimistic mode."""
    fake_state = State(
        "light.test",
        "on",
        {
            "brightness": 95,
            "hs_color": [100, 100],
            "effect": "random",
            "color_temp": 100,
        },
    )
    mock_restore_cache(hass, (fake_state,))

    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,"
                    "{{ brightness|d }},"
                    "{{ color_temp|d }},"
                    "{{ red|d }}-"
                    "{{ green|d }}-"
                    "{{ blue|d }},"
                    "{{ hue|d }}-"
                    "{{ sat|d }}",
                    "command_off_template": "off",
                    "effect_list": ["colorloop", "random"],
                    "optimistic": True,
                    "state_template": '{{ value.split(",")[0] }}',
                    "color_temp_template": '{{ value.split(",")[2] }}',
                    "red_template": '{{ value.split(",")[3].' 'split("-")[0] }}',
                    "green_template": '{{ value.split(",")[3].' 'split("-")[1] }}',
                    "blue_template": '{{ value.split(",")[3].' 'split("-")[2] }}',
                    "effect_template": '{{ value.split(",")[4] }}',
                    "qos": 2,
                }
            }
        },
    )
    await hass.async_block_till_done()
    mqtt_mock = await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("hs_color") == (100, 100)
    assert state.attributes.get("effect") == "random"
    assert state.attributes.get("color_temp") is None  # hs_color has priority
    assert state.attributes.get(ATTR_ASSUMED_STATE)

    await common.async_turn_off(hass, "light.test")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "off", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_OFF

    await common.async_turn_on(hass, "light.test")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,--,-", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    # Set color_temp
    await common.async_turn_on(hass, "light.test", color_temp=70)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,70,--,-", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("color_temp") == 70

    # Set full brightness
    await common.async_turn_on(hass, "light.test", brightness=255)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,255,,--,-", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    # Full brightness - no scaling of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[255, 128, 0])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,255-128-0,30.118-100.0", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") == (255, 128, 0)

    # Full brightness - normalization of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[128, 64, 0])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,255-127-0,30.0-100.0", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") == (255, 127, 0)

    # Set half brightness
    await common.async_turn_on(hass, "light.test", brightness=128)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,128,,--,-", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    # Half brightness - scaling of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[0, 255, 128])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,0-128-64,150.118-100.0", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") == (0, 255, 128)

    # Half brightness - normalization+scaling of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[0, 32, 16])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,0-128-64,150.0-100.0", 2, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("rgb_color") == (0, 255, 127)


async def test_sending_mqtt_commands_non_optimistic_brightness_template(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test the sending of command in optimistic mode."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "effect_list": ["rainbow", "colorloop"],
                    "state_topic": "test_light_rgb",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,"
                    "{{ brightness|d }},"
                    "{{ color_temp|d }},"
                    "{{ red|d }}-"
                    "{{ green|d }}-"
                    "{{ blue|d }},"
                    "{{ hue }}-"
                    "{{ sat }}",
                    "command_off_template": "off",
                    "state_template": '{{ value.split(",")[0] }}',
                    "brightness_template": '{{ value.split(",")[1] }}',
                    "color_temp_template": '{{ value.split(",")[2] }}',
                    "red_template": '{{ value.split(",")[3].' 'split("-")[0] }}',
                    "green_template": '{{ value.split(",")[3].' 'split("-")[1] }}',
                    "blue_template": '{{ value.split(",")[3].' 'split("-")[2] }}',
                    "effect_template": '{{ value.split(",")[4] }}',
                }
            }
        },
    )
    await hass.async_block_till_done()
    mqtt_mock = await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert not state.attributes.get("brightness")
    assert not state.attributes.get("hs_color")
    assert not state.attributes.get("effect")
    assert not state.attributes.get("color_temp")
    assert not state.attributes.get(ATTR_ASSUMED_STATE)

    await common.async_turn_off(hass, "light.test")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "off", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN

    await common.async_turn_on(hass, "light.test")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,--,-", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN

    # Set color_temp
    await common.async_turn_on(hass, "light.test", color_temp=70)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,70,--,-", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert not state.attributes.get("color_temp")

    # Set full brightness
    await common.async_turn_on(hass, "light.test", brightness=255)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,255,,--,-", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert not state.attributes.get("brightness")

    # Full brightness - no scaling of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[255, 128, 0])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,255-128-0,30.118-100.0", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert not state.attributes.get("rgb_color")

    # Full brightness - normalization of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[128, 64, 0])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,255-127-0,30.0-100.0", 0, False
    )
    mqtt_mock.async_publish.reset_mock()

    # Set half brightness
    await common.async_turn_on(hass, "light.test", brightness=128)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,128,,--,-", 0, False
    )
    mqtt_mock.async_publish.reset_mock()

    # Half brightness - no scaling of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[0, 255, 128])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,0-255-128,150.118-100.0", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")

    # Half brightness - normalization but no scaling of RGB values sent over MQTT
    await common.async_turn_on(hass, "light.test", rgb_color=[0, 32, 16])
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,,,0-255-127,150.0-100.0", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")


async def test_effect(hass: HomeAssistant, mqtt_mock_entry_with_yaml_config) -> None:
    """Test effect sent over MQTT in optimistic mode."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "effect_list": ["rainbow", "colorloop"],
                    "name": "test",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,{{ effect }}",
                    "command_off_template": "off",
                    "qos": 0,
                }
            }
        },
    )
    await hass.async_block_till_done()
    mqtt_mock = await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get(ATTR_SUPPORTED_FEATURES) == 44

    await common.async_turn_on(hass, "light.test")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert not state.attributes.get("effect")

    await common.async_turn_on(hass, "light.test", effect="rainbow")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,rainbow", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("effect") == "rainbow"

    await common.async_turn_on(hass, "light.test", effect="colorloop")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,colorloop", 0, False
    )
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("effect") == "colorloop"


async def test_flash(hass: HomeAssistant, mqtt_mock_entry_with_yaml_config) -> None:
    """Test flash sent over MQTT in optimistic mode."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,{{ flash }}",
                    "command_off_template": "off",
                    "qos": 0,
                }
            }
        },
    )
    await hass.async_block_till_done()
    mqtt_mock = await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get(ATTR_SUPPORTED_FEATURES) == 40

    await common.async_turn_on(hass, "light.test")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    await common.async_turn_on(hass, "light.test", flash="short")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,short", 0, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    await common.async_turn_on(hass, "light.test", flash="long")
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,long", 0, False
    )
    state = hass.states.get("light.test")
    assert state.state == STATE_ON


async def test_transition(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test for transition time being sent when included."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,{{ transition }}",
                    "command_off_template": "off,{{ transition|int|d }}",
                    "qos": 1,
                }
            }
        },
    )
    await hass.async_block_till_done()
    mqtt_mock = await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN

    assert state.attributes.get(ATTR_SUPPORTED_FEATURES) == 40

    await common.async_turn_on(hass, "light.test", transition=10.0)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "on,10.0", 1, False
    )
    mqtt_mock.async_publish.reset_mock()
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    await common.async_turn_off(hass, "light.test", transition=20.0)
    mqtt_mock.async_publish.assert_called_once_with(
        "test_light_rgb/set", "off,20", 1, False
    )
    state = hass.states.get("light.test")
    assert state.state == STATE_OFF


async def test_invalid_values(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test that invalid values are ignored."""
    assert await async_setup_component(
        hass,
        mqtt.DOMAIN,
        {
            mqtt.DOMAIN: {
                light.DOMAIN: {
                    "schema": "template",
                    "name": "test",
                    "effect_list": ["rainbow", "colorloop"],
                    "state_topic": "test_light_rgb",
                    "command_topic": "test_light_rgb/set",
                    "command_on_template": "on,"
                    "{{ brightness|d }},"
                    "{{ color_temp|d }},"
                    "{{ red|d }}-"
                    "{{ green|d }}-"
                    "{{ blue|d }},"
                    "{{ effect|d }}",
                    "command_off_template": "off",
                    "state_template": '{{ value.split(",")[0] }}',
                    "brightness_template": '{{ value.split(",")[1] }}',
                    "color_temp_template": '{{ value.split(",")[2] }}',
                    "red_template": '{{ value.split(",")[3].' 'split("-")[0] }}',
                    "green_template": '{{ value.split(",")[3].' 'split("-")[1] }}',
                    "blue_template": '{{ value.split(",")[3].' 'split("-")[2] }}',
                    "effect_template": '{{ value.split(",")[4] }}',
                }
            }
        },
    )
    await hass.async_block_till_done()
    await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.state == STATE_UNKNOWN
    assert state.attributes.get("rgb_color") is None
    assert state.attributes.get("brightness") is None
    assert state.attributes.get("color_temp") is None
    assert state.attributes.get("effect") is None
    assert not state.attributes.get(ATTR_ASSUMED_STATE)

    # turn on the light
    async_fire_mqtt_message(hass, "test_light_rgb", "on,255,215,255-255-255,rainbow")

    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("brightness") == 255
    assert state.attributes.get("color_temp") is None  # hs_color has priority
    assert state.attributes.get("rgb_color") == (255, 255, 255)
    assert state.attributes.get("effect") == "rainbow"

    # bad state value
    async_fire_mqtt_message(hass, "test_light_rgb", "offf")

    # state should not have changed
    state = hass.states.get("light.test")
    assert state.state == STATE_ON

    # bad brightness values
    async_fire_mqtt_message(hass, "test_light_rgb", "on,off,255-255-255")

    # brightness should not have changed
    state = hass.states.get("light.test")
    assert state.attributes.get("brightness") == 255

    # bad color values
    async_fire_mqtt_message(hass, "test_light_rgb", "on,255,a-b-c")

    # color should not have changed
    state = hass.states.get("light.test")
    assert state.attributes.get("rgb_color") == (255, 255, 255)

    # Unset color and set a valid color temperature
    async_fire_mqtt_message(hass, "test_light_rgb", "on,,215,None-None-None")
    state = hass.states.get("light.test")
    assert state.state == STATE_ON
    assert state.attributes.get("color_temp") == 215

    # bad color temp values
    async_fire_mqtt_message(hass, "test_light_rgb", "on,,off,")

    # color temp should not have changed
    state = hass.states.get("light.test")
    assert state.attributes.get("color_temp") == 215

    # bad effect value
    async_fire_mqtt_message(hass, "test_light_rgb", "on,255,a-b-c,white")

    # effect should not have changed
    state = hass.states.get("light.test")
    assert state.attributes.get("effect") == "rainbow"


async def test_availability_when_connection_lost(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test availability after MQTT disconnection."""
    await help_test_availability_when_connection_lost(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_availability_without_topic(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test availability without defined availability topic."""
    await help_test_availability_without_topic(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_default_availability_payload(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test availability by default payload with defined topic."""
    await help_test_default_availability_payload(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_custom_availability_payload(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test availability by custom payload with defined topic."""
    await help_test_custom_availability_payload(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_setting_attribute_via_mqtt_json_message(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test the setting of attribute via MQTT with JSON payload."""
    await help_test_setting_attribute_via_mqtt_json_message(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_setting_blocked_attribute_via_mqtt_json_message(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test the setting of attribute via MQTT with JSON payload."""
    await help_test_setting_blocked_attribute_via_mqtt_json_message(
        hass,
        mqtt_mock_entry_no_yaml_config,
        light.DOMAIN,
        DEFAULT_CONFIG,
        MQTT_LIGHT_ATTRIBUTES_BLOCKED,
    )


async def test_setting_attribute_with_template(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test the setting of attribute via MQTT with JSON payload."""
    await help_test_setting_attribute_with_template(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_update_with_json_attrs_not_dict(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config, caplog
) -> None:
    """Test attributes get extracted from a JSON result."""
    await help_test_update_with_json_attrs_not_dict(
        hass,
        mqtt_mock_entry_with_yaml_config,
        caplog,
        light.DOMAIN,
        DEFAULT_CONFIG,
    )


async def test_update_with_json_attrs_bad_json(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config, caplog
) -> None:
    """Test attributes get extracted from a JSON result."""
    await help_test_update_with_json_attrs_bad_json(
        hass,
        mqtt_mock_entry_with_yaml_config,
        caplog,
        light.DOMAIN,
        DEFAULT_CONFIG,
    )


async def test_discovery_update_attr(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config, caplog
) -> None:
    """Test update of discovered MQTTAttributes."""
    await help_test_discovery_update_attr(
        hass,
        mqtt_mock_entry_no_yaml_config,
        caplog,
        light.DOMAIN,
        DEFAULT_CONFIG,
    )


async def test_unique_id(hass: HomeAssistant, mqtt_mock_entry_with_yaml_config) -> None:
    """Test unique id option only creates one light per unique_id."""
    config = {
        mqtt.DOMAIN: {
            light.DOMAIN: [
                {
                    "name": "Test 1",
                    "schema": "template",
                    "state_topic": "test-topic",
                    "command_topic": "test_topic",
                    "command_on_template": "on,{{ transition }}",
                    "command_off_template": "off,{{ transition|d }}",
                    "unique_id": "TOTALLY_UNIQUE",
                },
                {
                    "name": "Test 2",
                    "schema": "template",
                    "state_topic": "test-topic2",
                    "command_topic": "test_topic2",
                    "command_on_template": "on,{{ transition }}",
                    "command_off_template": "off,{{ transition|d }}",
                    "unique_id": "TOTALLY_UNIQUE",
                },
            ]
        }
    }
    await help_test_unique_id(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, config
    )


async def test_discovery_removal(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config, caplog
) -> None:
    """Test removal of discovered mqtt_json lights."""
    data = (
        '{ "name": "test",'
        '  "schema": "template",'
        '  "command_topic": "test_topic",'
        '  "command_on_template": "on",'
        '  "command_off_template": "off"}'
    )
    await help_test_discovery_removal(
        hass, mqtt_mock_entry_no_yaml_config, caplog, light.DOMAIN, data
    )


async def test_discovery_update_light(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config, caplog
) -> None:
    """Test update of discovered light."""
    config1 = {
        "name": "Beer",
        "schema": "template",
        "state_topic": "test_topic",
        "command_topic": "test_topic",
        "command_on_template": "on",
        "command_off_template": "off",
    }
    config2 = {
        "name": "Milk",
        "schema": "template",
        "state_topic": "test_topic",
        "command_topic": "test_topic",
        "command_on_template": "on",
        "command_off_template": "off",
    }
    await help_test_discovery_update(
        hass, mqtt_mock_entry_no_yaml_config, caplog, light.DOMAIN, config1, config2
    )


async def test_discovery_update_unchanged_light(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config, caplog
) -> None:
    """Test update of discovered light."""
    data1 = (
        '{ "name": "Beer",'
        '  "schema": "template",'
        '  "state_topic": "test_topic",'
        '  "command_topic": "test_topic",'
        '  "command_on_template": "on",'
        '  "command_off_template": "off"}'
    )
    with patch(
        "homeassistant.components.mqtt.light.schema_template.MqttLightTemplate.discovery_update"
    ) as discovery_update:
        await help_test_discovery_update_unchanged(
            hass,
            mqtt_mock_entry_no_yaml_config,
            caplog,
            light.DOMAIN,
            data1,
            discovery_update,
        )


@pytest.mark.no_fail_on_log_exception
async def test_discovery_broken(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config, caplog
) -> None:
    """Test handling of bad discovery message."""
    data1 = '{ "name": "Beer" }'
    data2 = (
        '{ "name": "Milk",'
        '  "schema": "template",'
        '  "state_topic": "test_topic",'
        '  "command_topic": "test_topic",'
        '  "command_on_template": "on",'
        '  "command_off_template": "off"}'
    )
    await help_test_discovery_broken(
        hass, mqtt_mock_entry_no_yaml_config, caplog, light.DOMAIN, data1, data2
    )


async def test_entity_device_info_with_connection(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test MQTT light device registry integration."""
    await help_test_entity_device_info_with_connection(
        hass, mqtt_mock_entry_no_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_entity_device_info_with_identifier(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test MQTT light device registry integration."""
    await help_test_entity_device_info_with_identifier(
        hass, mqtt_mock_entry_no_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_entity_device_info_update(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test device registry update."""
    await help_test_entity_device_info_update(
        hass, mqtt_mock_entry_no_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_entity_device_info_remove(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test device registry remove."""
    await help_test_entity_device_info_remove(
        hass, mqtt_mock_entry_no_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_entity_id_update_subscriptions(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test MQTT subscriptions are managed when entity_id is updated."""
    await help_test_entity_id_update_subscriptions(
        hass, mqtt_mock_entry_with_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_entity_id_update_discovery_update(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test MQTT discovery update when entity_id is updated."""
    await help_test_entity_id_update_discovery_update(
        hass, mqtt_mock_entry_no_yaml_config, light.DOMAIN, DEFAULT_CONFIG
    )


async def test_entity_debug_info_message(
    hass: HomeAssistant, mqtt_mock_entry_no_yaml_config
) -> None:
    """Test MQTT debug info."""
    config = {
        mqtt.DOMAIN: {
            light.DOMAIN: {
                "schema": "template",
                "name": "test",
                "command_topic": "test-topic",
                "command_on_template": "ON",
                "command_off_template": "off,{{ transition|d }}",
                "state_template": '{{ value.split(",")[0] }}',
            }
        }
    }
    await help_test_entity_debug_info_message(
        hass,
        mqtt_mock_entry_no_yaml_config,
        light.DOMAIN,
        config,
        light.SERVICE_TURN_ON,
    )


async def test_max_mireds(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config
) -> None:
    """Test setting min_mireds and max_mireds."""
    config = {
        light.DOMAIN: {
            "schema": "template",
            "name": "test",
            "command_topic": "test_max_mireds/set",
            "command_on_template": "on",
            "command_off_template": "off",
            "color_temp_template": "{{ value }}",
            "max_mireds": 370,
        }
    }

    assert await async_setup_component(hass, mqtt.DOMAIN, {mqtt.DOMAIN: config})
    await hass.async_block_till_done()
    await mqtt_mock_entry_with_yaml_config()

    state = hass.states.get("light.test")
    assert state.attributes.get("min_mireds") == 153
    assert state.attributes.get("max_mireds") == 370


@pytest.mark.parametrize(
    "service,topic,parameters,payload,template,tpl_par,tpl_output",
    [
        (
            light.SERVICE_TURN_ON,
            "command_topic",
            None,
            "on,",
            None,
            None,
            None,
        ),
        (
            light.SERVICE_TURN_OFF,
            "command_topic",
            None,
            "off,",
            None,
            None,
            None,
        ),
    ],
)
async def test_publishing_with_custom_encoding(
    hass: HomeAssistant,
    mqtt_mock_entry_with_yaml_config,
    caplog,
    service,
    topic,
    parameters,
    payload,
    template,
    tpl_par,
    tpl_output,
) -> None:
    """Test publishing MQTT payload with different encoding."""
    domain = light.DOMAIN
    config = copy.deepcopy(DEFAULT_CONFIG)
    if topic == "effect_command_topic":
        config[mqtt.DOMAIN][domain]["effect_list"] = ["random", "color_loop"]

    await help_test_publishing_with_custom_encoding(
        hass,
        mqtt_mock_entry_with_yaml_config,
        caplog,
        domain,
        config,
        service,
        topic,
        parameters,
        payload,
        template,
        tpl_par=tpl_par,
        tpl_output=tpl_output,
    )


async def test_reloadable(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config, caplog, tmp_path
) -> None:
    """Test reloading the MQTT platform."""
    domain = light.DOMAIN
    config = DEFAULT_CONFIG
    await help_test_reloadable(
        hass, mqtt_mock_entry_with_yaml_config, caplog, tmp_path, domain, config
    )


@pytest.mark.parametrize(
    "topic,value,attribute,attribute_value,init_payload",
    [
        ("state_topic", "on", None, "on", None),
    ],
)
async def test_encoding_subscribable_topics(
    hass: HomeAssistant,
    mqtt_mock_entry_with_yaml_config,
    caplog,
    topic,
    value,
    attribute,
    attribute_value,
    init_payload,
) -> None:
    """Test handling of incoming encoded payload."""
    config = copy.deepcopy(DEFAULT_CONFIG[mqtt.DOMAIN][light.DOMAIN])
    config["state_template"] = "{{ value }}"
    await help_test_encoding_subscribable_topics(
        hass,
        mqtt_mock_entry_with_yaml_config,
        caplog,
        light.DOMAIN,
        config,
        topic,
        value,
        attribute,
        attribute_value,
        init_payload,
    )


async def test_setup_manual_entity_from_yaml(hass: HomeAssistant) -> None:
    """Test setup manual configured MQTT entity."""
    platform = light.DOMAIN
    await help_test_setup_manual_entity_from_yaml(hass, DEFAULT_CONFIG)
    assert hass.states.get(f"{platform}.test")


async def test_unload_entry(
    hass: HomeAssistant, mqtt_mock_entry_with_yaml_config, tmp_path
) -> None:
    """Test unloading the config entry."""
    domain = light.DOMAIN
    config = DEFAULT_CONFIG
    await help_test_unload_config_entry_with_platform(
        hass, mqtt_mock_entry_with_yaml_config, tmp_path, domain, config
    )
