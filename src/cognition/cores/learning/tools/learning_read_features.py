"""Read waveform features (never raw samples) for one channel."""

from cognition.agentkit.tools import choose_format, tool, tool_error
from cognition.cores.context import CoreContext


@tool("learning", "read")
def learning_read_features(
    ctx: CoreContext, channel: str, window: int = 256, response_format: str = "concise"
) -> dict:
    """Read RMS, kurtosis, crest factor and dominant frequency of a waveform channel.

    Use when a vibration or acoustic channel looks abnormal and you need its shape.
    Do not use on scalar channels, and do not expect raw samples: only features are returned.

    Args:
        channel: A waveform channel id such as "drive_vibration".
        window: Number of samples to analyse, 16 to 1024.
        response_format: "concise" or "detailed" (adds the healthy baseline features).
    Returns:
        Features for the channel, with baseline features when detailed.
    """
    bus = ctx.platform.signals
    try:
        now = bus.features(ctx.plant_id, channel, window)
    except KeyError:
        return tool_error(f"Unknown channel '{channel}'", "Call learning_list_channels first.")
    except ValueError as error:
        return tool_error(str(error), "Use learning_compare_baseline for scalar channels.")
    concise = {"channel": channel, "rms": now.rms, "kurtosis": now.kurtosis, "unit": "see list"}
    detailed = now.model_dump(mode="json") | {
        "baseline": bus.baseline_features(ctx.plant_id, channel, window).model_dump(mode="json")
    }
    return choose_format(concise, detailed, response_format)
