from ._registry import register_metric
from .base import BaseMetric
from src.config.learning_dynamics import BaseMetricConfig


@register_metric("norm")
class L2Norm(BaseMetric):
    """
    Class for computing the L2 norm of the activations.
    """

    def __init__(self, metric_config: BaseMetricConfig):
        super().__init__(metric_config)

        # TODO: Implement this
