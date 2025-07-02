"""Constants for the ML Model integration."""

from homeassistant.const import Platform

DOMAIN = "ml_model"
PLATFORMS = [Platform.SENSOR]

CONF_START = "start"
CONF_END = "end"
CONF_DURATION = "duration"
CONF_PERIOD_KEYS = [CONF_START, CONF_END, CONF_DURATION]

CONF_TYPE_TIME = "time"
CONF_TYPE_RATIO = "ratio"
CONF_TYPE_COUNT = "count"
CONF_TYPE_KEYS = [CONF_TYPE_TIME, CONF_TYPE_RATIO, CONF_TYPE_COUNT]

CONF_SOURCE_SENSOR = "source"
CONF_UNIT_TIME = "unit_time"
CONF_MAX_SUB_INTERVAL = "max_sub_interval"

CONF_METHOD = "batch_method"
CONF_CONDITION = "count_condition"
METHOD_CHANGEPOINT = "change_point"
METHOD_NUMSAMPLES = "num_samples"
METHOD_TIMEDURATION = "time_duration"
BATCH_METHODS = [METHOD_CHANGEPOINT, METHOD_NUMSAMPLES, METHOD_TIMEDURATION]

DEFAULT_NAME = "unnamed data loader"
