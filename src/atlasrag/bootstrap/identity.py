from dataclasses import dataclass

from atlasrag.contracts.identity import ProvisioningPolicy


@dataclass(frozen=True, slots=True)
class ConfiguredProvisioningPolicy(ProvisioningPolicy):
    """Provisioning policy loaded from application configuration."""

    enabled: bool

    def jit_enabled(self) -> bool:
        return self.enabled
