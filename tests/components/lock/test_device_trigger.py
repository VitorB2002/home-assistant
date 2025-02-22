"""The tests for Lock device triggers."""
from datetime import timedelta

import pytest

import homeassistant.components.automation as automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.components.lock import DOMAIN
from homeassistant.const import (
    STATE_JAMMED,
    STATE_LOCKED,
    STATE_LOCKING,
    STATE_UNLOCKED,
    STATE_UNLOCKING,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import RegistryEntryHider
from homeassistant.setup import async_setup_component
import homeassistant.util.dt as dt_util

from tests.common import (
    MockConfigEntry,
    assert_lists_same,
    async_fire_time_changed,
    async_get_device_automation_capabilities,
    async_get_device_automations,
    async_mock_service,
)
from tests.components.blueprint.conftest import stub_blueprint_populate  # noqa: F401


@pytest.fixture
def calls(hass):
    """Track calls to a mock service."""
    return async_mock_service(hass, "test", "automation")


async def test_get_triggers(hass, device_registry, entity_registry):
    """Test we get the expected triggers from a lock."""
    config_entry = MockConfigEntry(domain="test", data={})
    config_entry.add_to_hass(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "12:34:56:AB:CD:EF")},
    )
    entity_registry.async_get_or_create(
        DOMAIN, "test", "5678", device_id=device_entry.id
    )
    expected_triggers = [
        {
            "platform": "device",
            "domain": DOMAIN,
            "type": trigger,
            "device_id": device_entry.id,
            "entity_id": f"{DOMAIN}.test_5678",
            "metadata": {"secondary": False},
        }
        for trigger in ["locked", "unlocked", "unlocking", "locking", "jammed"]
    ]
    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device_entry.id
    )
    assert_lists_same(triggers, expected_triggers)


@pytest.mark.parametrize(
    "hidden_by,entity_category",
    (
        (RegistryEntryHider.INTEGRATION, None),
        (RegistryEntryHider.USER, None),
        (None, EntityCategory.CONFIG),
        (None, EntityCategory.DIAGNOSTIC),
    ),
)
async def test_get_triggers_hidden_auxiliary(
    hass,
    device_registry,
    entity_registry,
    hidden_by,
    entity_category,
):
    """Test we get the expected triggers from a hidden or auxiliary entity."""
    config_entry = MockConfigEntry(domain="test", data={})
    config_entry.add_to_hass(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "12:34:56:AB:CD:EF")},
    )
    entity_registry.async_get_or_create(
        DOMAIN,
        "test",
        "5678",
        device_id=device_entry.id,
        entity_category=entity_category,
        hidden_by=hidden_by,
    )
    expected_triggers = [
        {
            "platform": "device",
            "domain": DOMAIN,
            "type": trigger,
            "device_id": device_entry.id,
            "entity_id": f"{DOMAIN}.test_5678",
            "metadata": {"secondary": True},
        }
        for trigger in ["locked", "unlocked", "unlocking", "locking", "jammed"]
    ]
    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device_entry.id
    )
    assert_lists_same(triggers, expected_triggers)


async def test_get_trigger_capabilities(hass, device_registry, entity_registry):
    """Test we get the expected capabilities from a lock."""
    config_entry = MockConfigEntry(domain="test", data={})
    config_entry.add_to_hass(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, "12:34:56:AB:CD:EF")},
    )
    entity_registry.async_get_or_create(
        DOMAIN, "test", "5678", device_id=device_entry.id
    )

    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device_entry.id
    )
    assert len(triggers) == 5
    for trigger in triggers:
        capabilities = await async_get_device_automation_capabilities(
            hass, DeviceAutomationType.TRIGGER, trigger
        )
        assert capabilities == {
            "extra_fields": [
                {"name": "for", "optional": True, "type": "positive_time_period_dict"}
            ]
        }


async def test_if_fires_on_state_change(hass, calls):
    """Test for turn_on and turn_off triggers firing."""
    hass.states.async_set("lock.entity", STATE_UNLOCKED)

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": "",
                        "entity_id": "lock.entity",
                        "type": "locked",
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "some": (
                                "locked - {{ trigger.platform}} - "
                                "{{ trigger.entity_id}} - {{ trigger.from_state.state}} - "
                                "{{ trigger.to_state.state}} - {{ trigger.for }}"
                            )
                        },
                    },
                },
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": "",
                        "entity_id": "lock.entity",
                        "type": "unlocked",
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "some": (
                                "unlocked - {{ trigger.platform}} - "
                                "{{ trigger.entity_id}} - {{ trigger.from_state.state}} - "
                                "{{ trigger.to_state.state}} - {{ trigger.for }}"
                            )
                        },
                    },
                },
            ]
        },
    )

    # Fake that the entity is turning on.
    hass.states.async_set("lock.entity", STATE_LOCKED)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data[
        "some"
    ] == "locked - device - {} - unlocked - locked - None".format("lock.entity")

    # Fake that the entity is turning off.
    hass.states.async_set("lock.entity", STATE_UNLOCKED)
    await hass.async_block_till_done()
    assert len(calls) == 2
    assert calls[1].data[
        "some"
    ] == "unlocked - device - {} - locked - unlocked - None".format("lock.entity")


async def test_if_fires_on_state_change_with_for(hass, calls):
    """Test for triggers firing with delay."""
    entity_id = f"{DOMAIN}.entity"
    hass.states.async_set(entity_id, STATE_UNLOCKED)

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": "",
                        "entity_id": entity_id,
                        "type": "locked",
                        "for": {"seconds": 5},
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "some": "turn_off {{ trigger.%s }}"
                            % "}} - {{ trigger.".join(
                                (
                                    "platform",
                                    "entity_id",
                                    "from_state.state",
                                    "to_state.state",
                                    "for",
                                )
                            )
                        },
                    },
                },
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": "",
                        "entity_id": entity_id,
                        "type": "unlocking",
                        "for": {"seconds": 5},
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "some": "turn_on {{ trigger.%s }}"
                            % "}} - {{ trigger.".join(
                                (
                                    "platform",
                                    "entity_id",
                                    "from_state.state",
                                    "to_state.state",
                                    "for",
                                )
                            )
                        },
                    },
                },
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": "",
                        "entity_id": entity_id,
                        "type": "jammed",
                        "for": {"seconds": 5},
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "some": "turn_off {{ trigger.%s }}"
                            % "}} - {{ trigger.".join(
                                (
                                    "platform",
                                    "entity_id",
                                    "from_state.state",
                                    "to_state.state",
                                    "for",
                                )
                            )
                        },
                    },
                },
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": "",
                        "entity_id": entity_id,
                        "type": "locking",
                        "for": {"seconds": 5},
                    },
                    "action": {
                        "service": "test.automation",
                        "data_template": {
                            "some": "turn_on {{ trigger.%s }}"
                            % "}} - {{ trigger.".join(
                                (
                                    "platform",
                                    "entity_id",
                                    "from_state.state",
                                    "to_state.state",
                                    "for",
                                )
                            )
                        },
                    },
                },
            ]
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_UNLOCKED
    assert len(calls) == 0

    hass.states.async_set(entity_id, STATE_LOCKED)
    await hass.async_block_till_done()
    assert len(calls) == 0
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert len(calls) == 1
    await hass.async_block_till_done()
    assert (
        calls[0].data["some"]
        == f"turn_off device - {entity_id} - unlocked - locked - 0:00:05"
    )

    hass.states.async_set(entity_id, STATE_UNLOCKING)
    await hass.async_block_till_done()
    assert len(calls) == 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=16))
    await hass.async_block_till_done()
    assert len(calls) == 2
    await hass.async_block_till_done()
    assert (
        calls[1].data["some"]
        == f"turn_on device - {entity_id} - locked - unlocking - 0:00:05"
    )

    hass.states.async_set(entity_id, STATE_JAMMED)
    await hass.async_block_till_done()
    assert len(calls) == 2
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=21))
    await hass.async_block_till_done()
    assert len(calls) == 3
    await hass.async_block_till_done()
    assert (
        calls[2].data["some"]
        == f"turn_off device - {entity_id} - unlocking - jammed - 0:00:05"
    )

    hass.states.async_set(entity_id, STATE_LOCKING)
    await hass.async_block_till_done()
    assert len(calls) == 3
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=27))
    await hass.async_block_till_done()
    assert len(calls) == 4
    await hass.async_block_till_done()
    assert (
        calls[3].data["some"]
        == f"turn_on device - {entity_id} - jammed - locking - 0:00:05"
    )
