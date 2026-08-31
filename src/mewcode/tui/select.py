"""Provider selection helpers."""

from textual.widgets import OptionList
from textual.widgets._option_list import Option

from ..config import ProviderConfig


def provider_options(providers: list[ProviderConfig]) -> OptionList:
    return OptionList(
        *(
            Option(f"{provider.name} ({provider.model})", id=str(index))
            for index, provider in enumerate(providers)
        ),
        id="provider-selector",
    )
