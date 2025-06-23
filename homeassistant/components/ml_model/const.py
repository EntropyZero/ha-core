"""Constants for the ML Model integration."""

DOMAIN = "ml_model"

CONF_SOURCE_SENSOR = "source"
CONF_UNIT_TIME = "unit_time"
CONF_MAX_SUB_INTERVAL = "max_sub_interval"

METHOD_CHANGEPOINT = "change_point"
METHOD_NUMSAMPLES = "num_samples"
METHOD_TIMEDURATION = "time_duration"
BATCH_METHODS = [METHOD_CHANGEPOINT, METHOD_NUMSAMPLES, METHOD_TIMEDURATION]
