class EvaluationConfigurationError(Exception):
    pass


class UnknownTokenizerError(EvaluationConfigurationError):
    def __init__(self, name: str) -> None:
        super().__init__(f"unknown tokenizer: {name}")
        self.name = name


class FixtureManifestError(EvaluationConfigurationError):
    pass


class DatasetIntegrityError(EvaluationConfigurationError):
    pass


__all__ = [
    "DatasetIntegrityError",
    "EvaluationConfigurationError",
    "FixtureManifestError",
    "UnknownTokenizerError",
]
