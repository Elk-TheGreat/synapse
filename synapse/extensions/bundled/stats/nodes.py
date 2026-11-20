"""Sample plugin: descriptive statistics."""

from synapse.extensions.api import PluginAPI
from synapse.nodes.registry import NodeRegistry
from synapse.typesystem import DataType


def _numbers(value) -> list[float]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("expected an array of numbers")
    return [float(v) for v in value]


def register(registry: NodeRegistry, api: PluginAPI) -> None:
    @api.node(
        "stats.describe",
        "Describe",
        "Statistics",
        description="Mean, median, minimum, maximum and count of an array.",
        inputs=[api.input("values", DataType.ARRAY, [])],
        outputs=[api.output("stats", DataType.DICTIONARY), api.output("mean", DataType.FLOAT)],
    )
    def describe(ctx, inputs, params):
        values = sorted(_numbers(inputs.get("values")))
        if not values:
            return {"stats": {"count": 0}, "mean": 0.0}
        count = len(values)
        mean = sum(values) / count
        middle = count // 2
        median = values[middle] if count % 2 else (values[middle - 1] + values[middle]) / 2
        stats = {
            "count": count,
            "mean": mean,
            "median": median,
            "min": values[0],
            "max": values[-1],
            "sum": sum(values),
        }
        return {"stats": stats, "mean": mean}

    @api.node(
        "stats.zscore",
        "Z-Score",
        "Statistics",
        description="Standard score of each value against the sample mean and standard deviation.",
        inputs=[api.input("values", DataType.ARRAY, [])],
        outputs=[api.output("scores", DataType.ARRAY)],
    )
    def zscore(ctx, inputs, params):
        values = _numbers(inputs.get("values"))
        if len(values) < 2:
            return {"scores": [0.0 for _ in values]}
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        deviation = variance ** 0.5
        if deviation == 0:
            return {"scores": [0.0 for _ in values]}
        return {"scores": [(v - mean) / deviation for v in values]}
