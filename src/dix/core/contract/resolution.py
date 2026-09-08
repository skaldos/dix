from __future__ import annotations

from collections.abc import Mapping

from dix.core.model import ModelArtifactDefinition, ModelNotLoaded, ModelReference
from dix.core.norn import StrandDefinition, model_element

from .models import ContractDefinition


def resolve_contract_strand(
    contract: ContractDefinition,
    models: Mapping[ModelReference, ModelArtifactDefinition],
) -> StrandDefinition:
    """Resolve code-free model references into one local runtime strand."""

    def resolve(element):
        if element.type != "model":
            return element
        reference = element.config.get("reference")
        if not isinstance(reference, ModelReference):
            raise ModelNotLoaded(
                f"contract model endpoint has no valid reference: {contract.id}"
            )
        try:
            model = models[reference]
        except KeyError as exc:
            raise ModelNotLoaded(
                f"model is not loaded: {reference.use}@{reference.version!r}"
            ) from exc
        return model_element(model.definition)

    return StrandDefinition(
        id=contract.strand.id,
        input_element=resolve(contract.strand.input_element),
        output_element=resolve(contract.strand.output_element),
    )
