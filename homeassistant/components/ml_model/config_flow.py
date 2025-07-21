"""Config flow for ML Model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import voluptuous as vol

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    CONF_STATE,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
    SchemaOptionsFlowHandler,
)
from homeassistant.helpers.selector import (
    DurationSelector,
    DurationSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_CHANGEPOINT_KEYS,
    CONF_CONDITION,
    CONF_DURATION,
    CONF_METHOD,
    CONF_NUMSAMPLES_KEYS,
    CONF_SOURCE_SENSOR,
    CONF_TIMEDURATION_KEYS,
    DEFAULT_NAME,
    DOMAIN,
    METHOD_CHANGEPOINT,
    METHOD_NUMSAMPLES,
    METHOD_TIMEDURATION,
)

TIME_UNITS = [
    UnitOfTime.SECONDS,
    UnitOfTime.MINUTES,
    UnitOfTime.HOURS,
    UnitOfTime.DAYS,
]
BATCH_METHODS = [
    METHOD_CHANGEPOINT,
    METHOD_NUMSAMPLES,
    METHOD_TIMEDURATION,
]


async def validate_options(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate options selected."""

    if (
        sum(param in user_input for param in CONF_NUMSAMPLES_KEYS) != 2
        and sum(param in user_input for param in CONF_TIMEDURATION_KEYS) != 2
        and sum(param in user_input for param in CONF_CHANGEPOINT_KEYS) != 1
    ):
        raise SchemaFlowError("keys_do_not_match_method")

    handler.parent_handler._async_abort_entries_match({**handler.options, **user_input})  # noqa: SLF001

    return user_input


@callback
def entity_selector_compatible(
    handler: SchemaOptionsFlowHandler,
) -> selector.EntitySelector:
    """Return an entity selector with compatible entities."""
    current = handler.hass.states.get(handler.options[CONF_SOURCE_SENSOR])
    unit_of_measurement = (
        current.attributes.get(ATTR_UNIT_OF_MEASUREMENT) if current else None
    )

    entities = [
        ent.entity_id
        for ent in handler.hass.states.async_all(SENSOR_DOMAIN)
        if ent.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == unit_of_measurement
        and ent.domain in SENSOR_DOMAIN
    ]

    return selector.EntitySelector(
        selector.EntitySelectorConfig(include_entities=entities)
    )


async def _get_options_dict(handler: SchemaCommonFlowHandler | None) -> dict:
    # EVENTUALLY make an inference/train mode here
    return {
        vol.Optional(CONF_DURATION): DurationSelector(
            DurationSelectorConfig(enable_day=True, allow_negative=False)
        ),
        vol.Optional(CONF_CONDITION, default=1): selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, mode=selector.NumberSelectorMode.BOX),
        ),
    }


async def _get_options_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    return vol.Schema(await _get_options_dict(handler))


async def _get_config_schema(handler: SchemaCommonFlowHandler) -> vol.Schema:
    if handler is None or not isinstance(
        handler.parent_handler, SchemaOptionsFlowHandler
    ):
        entity_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(domain=SENSOR_DOMAIN)
        )
    else:
        entity_selector = entity_selector_compatible(handler.parent_handler)

    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=DEFAULT_NAME): TextSelector(),
            vol.Required(CONF_SOURCE_SENSOR): entity_selector,
            vol.Required(CONF_STATE): TextSelector(TextSelectorConfig(multiple=True)),
            vol.Required(
                CONF_METHOD, default=METHOD_CHANGEPOINT
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=BATCH_METHODS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key=CONF_METHOD,
                ),
            ),
        }
    )


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        schema=_get_config_schema,
        next_step="options",
    ),
    "options": SchemaFlowFormStep(
        schema=_get_options_schema,
        # validate_user_input=validate_options,
    ),
}
OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        schema=_get_options_schema,
        # validate_user_input=validate_options,
    ),
}


class MLModelFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for ML Model integration."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return cast(str, options[CONF_NAME])
