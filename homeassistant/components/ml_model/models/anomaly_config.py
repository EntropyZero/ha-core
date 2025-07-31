from dataclasses import dataclass
from datetime import timedelta


@dataclass
class AnomalyConfig:
    """Data for the Anomaly Detection integration."""

    entity_id: str
    entity_states: list[str]
    duration: timedelta | None
    batch_method: str
    count_condition: int | None
