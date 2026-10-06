from __future__ import annotations

from wf.artifact import Artifact


def emit_blif(art: Artifact) -> str:
    """Optional combinational dump. Default pipeline does not call this."""
    # ponytail: BLIF is config-gated; a wire stub until ABC verify is on
    return ".model wf\n.inputs wr_in\n.outputs wr_out\n.names wr_in wr_out\n1 1\n.end\n"
