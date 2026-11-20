"""Sample plugin: three text nodes written against the plugin API."""

from synapse.extensions.api import PluginAPI
from synapse.nodes.registry import NodeRegistry
from synapse.typesystem import DataType


def register(registry: NodeRegistry, api: PluginAPI) -> None:
    @api.node(
        "text.word_count",
        "Word Count",
        "Text Tools",
        description="Counts words, lines and characters in a string.",
        inputs=[api.input("text", DataType.STRING, "")],
        outputs=[api.output("words", DataType.INTEGER), api.output("lines", DataType.INTEGER), api.output("characters", DataType.INTEGER)],
    )
    def word_count(ctx, inputs, params):
        text = str(inputs.get("text") or "")
        return {
            "words": len(text.split()),
            "lines": 0 if not text else text.count("\n") + 1,
            "characters": len(text),
        }

    @api.node(
        "text.slugify",
        "Slugify",
        "Text Tools",
        description="Lower-cases text and joins runs of non-alphanumerics with single dashes.",
        inputs=[api.input("text", DataType.STRING, "")],
        outputs=[api.output("slug", DataType.STRING)],
    )
    def slugify(ctx, inputs, params):
        import re

        text = str(inputs.get("text") or "").strip().lower()
        return {"slug": re.sub(r"[^a-z0-9]+", "-", text).strip("-")}

    @api.node(
        "text.truncate",
        "Truncate",
        "Text Tools",
        description="Shortens text to a maximum length, optionally adding an ellipsis.",
        inputs=[api.input("text", DataType.STRING, "")],
        outputs=[api.output("text", DataType.STRING)],
        params=[
            api.param("length", "Length", "int", 80, minimum=1),
            api.param("ellipsis", "Add ellipsis", "bool", True),
        ],
    )
    def truncate(ctx, inputs, params):
        text = str(inputs.get("text") or "")
        limit = int(params.get("length") or 80)
        if len(text) <= limit:
            return {"text": text}
        cut = text[:limit].rstrip()
        return {"text": cut + ("..." if params.get("ellipsis", True) else "")}
