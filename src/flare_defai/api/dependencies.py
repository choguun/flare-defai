from typing import Optional

from fastapi import Depends

from flare_defai.ai.gemini import GeminiProvider
from flare_defai.blockchain.explorer import BlockExplorerService
from flare_defai.blockchain.flare import FlareProvider
from flare_defai.blockchain.transaction_validator import SecureTransactionValidator
from flare_defai.blockchain.contract_risk_analyzer import ContractRiskAnalyzer
from flare_defai.settings import settings

# Singleton instances
_flare_service: Optional[FlareProvider] = None
_explorer_service: Optional[BlockExplorerService] = None
_ai_provider: Optional[GeminiProvider] = None
_transaction_validator: Optional[SecureTransactionValidator] = None
_contract_risk_analyzer: Optional[ContractRiskAnalyzer] = None

def get_flare_service() -> FlareProvider:
    """Get Flare blockchain service singleton."""
    global _flare_service
    if _flare_service is None:
        _flare_service = FlareProvider(
            web3_provider_url=settings.web3_provider_url
        )
    return _flare_service

def get_explorer_service() -> BlockExplorerService:
    """Get block explorer service singleton."""
    global _explorer_service
    if _explorer_service is None:
        _explorer_service = BlockExplorerService(
            base_url=settings.web3_explorer_url,
        )
    return _explorer_service

def get_ai_provider() -> GeminiProvider:
    """Get AI provider singleton."""
    global _ai_provider
    if _ai_provider is None:
        _ai_provider = GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )
    return _ai_provider

def get_transaction_validator(
    flare_service: FlareProvider = Depends(get_flare_service),
    explorer_service: BlockExplorerService = Depends(get_explorer_service),
    ai_provider: GeminiProvider = Depends(get_ai_provider),
) -> SecureTransactionValidator:
    """Get secure transaction validator singleton."""
    global _transaction_validator
    if _transaction_validator is None:
        _transaction_validator = SecureTransactionValidator(
            web3=flare_service.w3,
            explorer_service=explorer_service,
            ai_provider=ai_provider,
        )
    return _transaction_validator

def get_contract_risk_analyzer(
    flare_service: FlareProvider = Depends(get_flare_service),
    explorer_service: BlockExplorerService = Depends(get_explorer_service),
    ai_provider: GeminiProvider = Depends(get_ai_provider),
) -> ContractRiskAnalyzer:
    """Get contract risk analyzer singleton."""
    global _contract_risk_analyzer
    if _contract_risk_analyzer is None:
        _contract_risk_analyzer = ContractRiskAnalyzer(
            web3=flare_service.w3,
            explorer_service=explorer_service,
            ai_provider=ai_provider,
        )
    return _contract_risk_analyzer 