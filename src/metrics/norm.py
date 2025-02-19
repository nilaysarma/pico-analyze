"""
Norm metrics compute the norm of weights, activations, gradients, etc.
"""

from ._registry import register_metric
from .base import BaseMetric
from src.config.learning_dynamics import BaseMetricConfig

import torch

from functools import partial

# Typing imports


@register_metric("norm")
class NormMetric(BaseMetric):
    """
    Base class for norm metrics; i.e. metrics that compute the norm of some component data.
    """

    def __init__(self, metric_config: BaseMetricConfig, *args):
        super().__init__(metric_config, *args)

        for component in self.metric_config.components:
            if component.data_type not in ["weights", "activations", "gradients"]:
                raise ValueError(f"Invalid data_type for: {component.data_type}")

        # NOTE: We use the torch.norm function to compute the norm of the data.
        if self.metric_config.norm_type == "frobenius":
            self.norm_function = partial(torch.norm, p="fro")
        elif self.metric_config.norm_type == "nuclear":
            self.norm_function = partial(torch.norm, p="nuc")
        elif self.metric_config.norm_type == "inf":
            self.norm_function = partial(torch.norm, p=float("inf"))
        else:
            raise ValueError(f"Invalid norm_type: {self.metric_config.norm_type}")

    def compute_metric(self, component_layer_data: torch.Tensor) -> float:
        """
        Computes the norm of the given component data.
        """
        return self.norm_function(component_layer_data).item()
