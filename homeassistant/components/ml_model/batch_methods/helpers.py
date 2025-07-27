"""Mapping of batch method names to their respective classes."""

from ..const import METHOD_CHANGEPOINT, METHOD_NUMSAMPLES, METHOD_TIMEDURATION
from .BatchMethod import BatchMethod
from .ChangePoint import ChangePoint
from .NumSamples import NumSamples
from .TimeDuration import TimeDuration

_NAME_TO_BATCH_METHOD: dict[str, type[BatchMethod]] = {
    METHOD_NUMSAMPLES: NumSamples,
    METHOD_TIMEDURATION: TimeDuration,
    METHOD_CHANGEPOINT: ChangePoint,
}
