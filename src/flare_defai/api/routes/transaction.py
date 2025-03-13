"""
Transaction Routes

API routes for handling blockchain transactions with security validation.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Request, Response
from pydantic import BaseModel, Field

from flare_defai.blockchain.transaction_validator import SecureTransactionValidator, TransactionRisk
from flare_defai.blockchain.contract_risk_analyzer import ContractRiskAnalyzer
from flare_defai.api.dependencies import get_transaction_validator, get_contract_risk_analyzer

router = APIRouter(
    prefix="/transaction",
    tags=["transaction"],
)

class TransactionRequest(BaseModel):
    """Request model for transaction validation."""
    transaction: Dict[str, Any] = Field(..., description="Transaction object")
    sender_address: str = Field(..., description="Address of transaction sender")
    

class TransactionValidationResponse(BaseModel):
    """Response model for transaction validation."""
    is_valid: bool = Field(..., description="Whether the transaction is valid")
    risk_level: str = Field(..., description="Transaction risk level")
    warnings: list[str] = Field(default_factory=list, description="Warning messages")
    recommendation: Optional[str] = Field(None, description="Human-readable recommendation")
    simulation_result: Optional[Dict[str, Any]] = Field(None, description="Transaction simulation results")
    ai_analysis: Optional[Dict[str, Any]] = Field(None, description="AI analysis results")
    

class ContractAnalysisRequest(BaseModel):
    """Request model for contract risk analysis."""
    contract_address: str = Field(..., description="Contract address to analyze")
    force_refresh: bool = Field(False, description="Force refresh of analysis")
    

class ContractAnalysisResponse(BaseModel):
    """Response model for contract risk analysis."""
    contract_address: str = Field(..., description="Contract address")
    risk_level: str = Field(..., description="Overall risk level")
    summary: str = Field(..., description="Human-readable summary")
    verification_status: Dict[str, Any] = Field(..., description="Verification status")
    findings: list[Dict[str, Any]] = Field(default_factory=list, description="Risk findings")
    ai_analysis: Optional[Dict[str, Any]] = Field(None, description="AI analysis results")
    

@router.post("/validate", response_model=TransactionValidationResponse)
async def validate_transaction(
    request: TransactionRequest,
    validator: SecureTransactionValidator = Depends(get_transaction_validator),
) -> TransactionValidationResponse:
    """
    Validate a transaction for security issues.
    
    This endpoint leverages TEE-secured environment for enhanced security analysis.
    """
    try:
        # Perform transaction validation
        result = await validator.validate_transaction(
            tx=request.transaction,
            sender_address=request.sender_address,
        )
        
        # Format response
        response = TransactionValidationResponse(
            is_valid=result.is_valid,
            risk_level=result.risk_level.value,
            warnings=result.warnings,
            recommendation=result.recommendation,
            simulation_result=result.simulation_result,
            ai_analysis=result.ai_analysis,
        )
        
        return response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transaction validation failed: {str(e)}"
        )
        

@router.post("/analyze-contract", response_model=ContractAnalysisResponse)
async def analyze_contract(
    request: ContractAnalysisRequest,
    risk_analyzer: ContractRiskAnalyzer = Depends(get_contract_risk_analyzer),
) -> ContractAnalysisResponse:
    """
    Perform comprehensive security analysis on a smart contract.
    
    This endpoint leverages TEE-secured AI for enhanced risk assessment.
    """
    try:
        # Perform contract analysis
        report = await risk_analyzer.analyze_contract(
            contract_address=request.contract_address,
            force_refresh=request.force_refresh,
        )
        
        # Format findings for API response
        formatted_findings = []
        for finding in report.findings:
            formatted_findings.append({
                "category": finding.category.value,
                "level": finding.level.value,
                "title": finding.title,
                "description": finding.description,
                "locations": finding.locations,
                "recommendation": finding.recommendation,
            })
        
        # Format response
        response = ContractAnalysisResponse(
            contract_address=report.contract_address,
            risk_level=report.risk_level.value,
            summary=report.summary,
            verification_status=report.verification_status,
            findings=formatted_findings,
            ai_analysis=report.ai_analysis,
        )
        
        return response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Contract analysis failed: {str(e)}"
        )
        

@router.post("/assess-transaction-contract")
async def assess_transaction_contract(
    request: TransactionRequest,
    risk_analyzer: ContractRiskAnalyzer = Depends(get_contract_risk_analyzer),
) -> Dict[str, Any]:
    """
    Assess the risk of a transaction specifically focusing on the contract being interacted with.
    
    This is a specialized endpoint for DeFi transactions where contract security is paramount.
    """
    try:
        # Perform transaction-specific contract risk assessment
        assessment = await risk_analyzer.assess_transaction_risk(
            tx=request.transaction,
            sender_address=request.sender_address,
        )
        
        return assessment
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Transaction contract assessment failed: {str(e)}"
        ) 