"""HIPAA-Bridge: local de-identification proxy for the Anthropic API.

PHI is stripped and replaced with deterministic tokens before any text
leaves the host; responses are re-identified locally. The token<->value
vault never leaves the machine.
"""

__version__ = "0.1.0"
