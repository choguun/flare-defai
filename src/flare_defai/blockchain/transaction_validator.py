"""
Transaction Validator Module

This module implements secure transaction handling and validation for the Flare network,
utilizing TEE-secured Gemini AI to enhance security checks.
"""

import json
import time
from enum import Enum
from typing import Any, Dict, List, Optional, override

import structlog
from pydantic import BaseModel
from web3 import Web3

from flare_defai.ai.gemini import GeminiProvider
from flare_defai.blockchain.explorer import BlockExplorerService

logger = structlog.get_logger(__name__)

class TransactionRisk(Enum):
    """Enum representing transaction risk levels."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    
    def _risk_value(self) -> int:
        """Get a numeric value for comparison based on risk level."""
        if self == TransactionRisk.SAFE:
            return 0
        elif self == TransactionRisk.LOW:
            return 1
        elif self == TransactionRisk.MEDIUM:
            return 2
        elif self == TransactionRisk.HIGH:
            return 3
        elif self == TransactionRisk.CRITICAL:
            return 4
        else:
            # Should never happen, but included for completeness
            return -1
    
    def __lt__(self, other: 'TransactionRisk') -> bool:
        """Less than comparison."""
        if not isinstance(other, TransactionRisk):
            return NotImplemented
        return self._risk_value() < other._risk_value()
        
    def __gt__(self, other: 'TransactionRisk') -> bool:
        """Greater than comparison."""
        if not isinstance(other, TransactionRisk):
            return NotImplemented
        return self._risk_value() > other._risk_value()
    
    @override
    def __eq__(self, other: object) -> bool:
        """Equal comparison."""
        if not isinstance(other, TransactionRisk):
            return False
        return self.value == other.value
    
    def __le__(self, other: 'TransactionRisk') -> bool:
        """Less than or equal comparison."""
        return self < other or self == other
    
    def __ge__(self, other: 'TransactionRisk') -> bool:
        """Greater than or equal comparison."""
        return self > other or self == other


class TransactionValidationResult(BaseModel):
    """Model for transaction validation results."""
    is_valid: bool
    risk_level: TransactionRisk
    warnings: List[str] = []
    simulation_result: Optional[Dict[str, Any]] = None
    ai_analysis: Optional[Dict[str, Any]] = None
    recommendation: Optional[str] = None


class SecureTransactionValidator:
    """
    Service for validating transactions securely before execution.
    
    This service leverages:
    1. TEE-secured environment for sensitive operations
    2. Gemini AI for transaction analysis
    3. On-chain simulation for outcome prediction
    4. Historical analysis for risk assessment
    """

    def __init__(
        self, 
        web3: Web3, 
        explorer_service: BlockExplorerService, 
        ai_provider: GeminiProvider
    ):
        """
        Initialize the transaction validator.
        
        Args:
            web3: Initialized Web3 instance
            explorer_service: Block explorer service
            ai_provider: AI provider for transaction analysis
        """
        self.web3 = web3
        self.explorer_service = explorer_service
        self.ai_provider = ai_provider
        self.logger = logger.bind(service="tx_validator")
        
        # Load known scam addresses (would typically come from a database or API)
        self.scam_addresses = set()
        self.known_safe_contracts = set()

        # Add WFLR contract and router to known safe contracts
        self.known_safe_contracts.add("0x1111111111111111111111111111111111111111".lower())  # FLR
        self.known_safe_contracts.add("0x1D80c49BbBCd1C0911346656B529DF9E5c2F783d".lower())  # WFLR
        self.known_safe_contracts.add("0xFbDa5F676cB37624f28265A144A48B0d6e87d3b6".lower())  # USDC
        self.known_safe_contracts.add("0x16b619B04c961E8f4F06C10B42FDAbb328980A89".lower())  # V2_FACTORY
        self.known_safe_contracts.add("0x4a1E5A90e9943467FAd1acea1E7F0e5e88472a1e".lower())  # UNISWAP_V2_ROUTER
        self.known_safe_contracts.add("0x8a1E35F5c98C4E85B36B7B253222eE17773b2781".lower())  # UNISWAP_V3_ROUTER
        self.known_safe_contracts.add("0x8A2578d23d4C532cC9A98FaD91C0523f5efDE652".lower())  # V3_FACTORY
        self.known_safe_contracts.add("0x0f3D8a38D4c74afBebc2c42695642f0e3acb15D3".lower())  # UNIVERSAL_ROUTER
        
    async def validate_transaction(
        self, 
        tx: Dict[str, Any],
        sender_address: str,
        sender_history: Optional[List[Dict[str, Any]]] = None,
    ) -> TransactionValidationResult:
        """
        Validate a transaction before execution.
        
        Args:
            tx: Transaction dictionary to validate
            sender_address: Address of transaction sender
            sender_history: Optional history of sender's transactions
            
        Returns:
            ValidationResult with security analysis
        """
        self.logger.info(
            "validating_transaction", 
            from_address=sender_address,
            to_address=tx.get("to"),
            value=tx.get("value"),
            gas=tx.get("gas")
        )
        
        warnings = []
        
        # 1. Basic validation checks
        basic_validation = self._perform_basic_validation(tx, sender_address)
        if not basic_validation["is_valid"]:
            return TransactionValidationResult(
                is_valid=False,
                risk_level=TransactionRisk.CRITICAL,
                warnings=basic_validation["warnings"],
                recommendation="Transaction contains critical errors and should not be executed."
            )
            
        warnings.extend(basic_validation["warnings"])
        
        # 2. Security checks - executed in TEE for security
        security_validation = self._perform_security_validation(tx, sender_address)
        if not security_validation["is_valid"]:
            return TransactionValidationResult(
                is_valid=False,
                risk_level=TransactionRisk.HIGH,
                warnings=security_validation["warnings"],
                recommendation="Transaction failed security validation and may be malicious."
            )
            
        warnings.extend(security_validation["warnings"])
        
        # 3. Simulation - predict transaction outcome
        simulation_result = self._simulate_transaction(tx, sender_address)
        
        # 4. AI analysis using Gemini within TEE
        ai_analysis = await self._perform_ai_analysis(tx, sender_address, simulation_result)
        
        # 5. Determine final risk level
        risk_level = self._calculate_risk_level(
            tx, 
            sender_address, 
            simulation_result,
            ai_analysis,
            warnings
        )
        
        # 6. Generate recommendation based on risk level
        recommendation = self._generate_recommendation(risk_level, warnings, ai_analysis)
        
        return TransactionValidationResult(
            is_valid=risk_level != TransactionRisk.CRITICAL,
            risk_level=risk_level,
            warnings=warnings,
            simulation_result=simulation_result,
            ai_analysis=ai_analysis,
            recommendation=recommendation
        )
        
    def _perform_basic_validation(
        self, 
        tx: Dict[str, Any], 
        sender_address: str
    ) -> Dict[str, Any]:
        """
        Perform basic transaction validation.
        
        Returns:
            Dict with is_valid flag and any warnings
        """
        warnings = []
        is_valid = True
        
        # Check for required fields
        required_fields = ["to", "value", "gas"]  # Removed "gasPrice" and "nonce" which might be auto-filled
        for field in required_fields:
            if field not in tx:
                warnings.append(f"Missing required field: {field}")
                is_valid = False
                
        # Check for valid addresses
        if tx.get("to") and not Web3.is_address(tx.get("to")):
            warnings.append("Invalid recipient address")
            is_valid = False
            
        if tx.get("from") and tx.get("from") != sender_address:
            warnings.append("Transaction sender doesn't match authenticated user")
            is_valid = False
            
        # Check for reasonable gas values - be more lenient
        if tx.get("gas", 0) > 10000000:  # Arbitrary high limit
            warnings.append("Unusually high gas limit")
        
        # Check if this is a known safe contract (like WFLR)
        to_address = tx.get("to", "").lower()
        # Common wrapped token contracts are usually safe
        if to_address in self.known_safe_contracts:
            self.logger.info("transaction_to_known_safe_contract", contract=to_address)
            
        # For now, consider common contracts like WFLR as safe
        # In a production system, this would be loaded from a verified contracts database
        wflr_contract = "0x1d80c49bbcd1c0911346656b529df9e5c2f783d".lower()
        if to_address.startswith(wflr_contract):
            self.logger.info("transaction_to_wflr_contract")
            # Add to known safe contracts for future reference
            self.known_safe_contracts.add(to_address)
        
        return {
            "is_valid": is_valid,
            "warnings": warnings
        }
        
    def _perform_security_validation(
        self, 
        tx: Dict[str, Any], 
        sender_address: str
    ) -> Dict[str, Any]:
        """
        Perform security validation within TEE.
        
        Returns:
            Dict with is_valid flag and any warnings
        """
        warnings = []
        is_valid = True
        
        # Check if recipient is a known scam address
        if tx.get("to") in self.scam_addresses:
            warnings.append("Recipient is a known scam address")
            is_valid = False
            
        # Check for unusual parameters that may indicate an attack
        if tx.get("data") and len(tx.get("data", "")) > 1000000:
            warnings.append("Unusually large data field")
            
        # Check for replay protection (EIP-155)
        # In real implementation, would verify chainId is present for EIP-155
        
        # Check for reasonable value
        if tx.get("value", 0) > self.web3.to_wei(1000, "ether"):
            warnings.append("Unusually high transaction value")
        
        return {
            "is_valid": is_valid,
            "warnings": warnings
        }
        
    def _simulate_transaction(
        self, 
        tx: Dict[str, Any], 
        sender_address: str
    ) -> Dict[str, Any]:
        """
        Simulate transaction execution to predict outcome.
        In production, this would use a service like Tenderly or local fork.
        
        Returns:
            Simulation result
        """
        try:
            # This is a simplified simulation
            # In production, would use a proper simulation service
            balance = self.web3.eth.get_balance(sender_address)
            tx_value = tx.get("value", 0)
            gas_price = tx.get("gasPrice", self.web3.eth.gas_price)
            gas_limit = tx.get("gas", 21000)
            max_fee = gas_price * gas_limit
            
            can_afford = balance >= (tx_value + max_fee)
            
            # Check if it's a contract interaction
            is_contract = False
            contract_verification = None
            if tx.get("to"):
                code = self.web3.eth.get_code(tx.get("to"))
                is_contract = len(code) > 0
                
                # In production, would check contract verification status
                # via explorer API
                contract_verification = {
                    "is_verified": tx.get("to") in self.known_safe_contracts,
                    "verification_platform": "FlareScan" if tx.get("to") in self.known_safe_contracts else None,
                }
            
            return {
                "can_afford": can_afford,
                "estimated_gas": gas_limit,  # In production, would call eth_estimateGas
                "is_contract_interaction": is_contract,
                "contract_verification": contract_verification,
                "simulation_time": int(time.time()),
                "simulation_successful": True
            }
        except Exception as e:
            self.logger.error("transaction_simulation_failed", error=str(e))
            return {
                "simulation_successful": False,
                "error": str(e)
            }
    
    async def _perform_ai_analysis(
        self, 
        tx: Dict[str, Any], 
        sender_address: str,
        simulation_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Use Gemini AI to analyze transaction for potential risks.
        
        Returns:
            AI analysis results
        """
        try:
            # Prepare transaction data for AI analysis
            # Convert any Decimal values to float to ensure JSON serialization works
            value_wei = tx.get("value", 0)
            gas_price_wei = tx.get("gasPrice", 0)
            
            tx_data = {
                "transaction": {
                    "from": sender_address,
                    "to": tx.get("to"),
                    "value": float(self.web3.from_wei(value_wei, "ether")),
                    "data": tx.get("data", "0x"),
                    "gas": tx.get("gas"),
                    "gasPrice": float(self.web3.from_wei(gas_price_wei, "gwei"))
                },
                "simulation_result": self._ensure_json_serializable(simulation_result)
            }
            
            # Format prompt for Gemini AI
            prompt = f"""
            Analyze this blockchain transaction for security risks:
            
            {json.dumps(tx_data, indent=2)}
            
            Focus on:
            1. Is this a known scam pattern?
            2. Does the transaction data contain suspicious functions?
            3. Is the gas price appropriate?
            4. Is the transaction value unusual?
            5. Is the transaction likely to succeed based on simulation?
            
            Provide a JSON response with:
            - security_score: 0-100 (higher is safer)
            - risk_assessment: Short description of risks
            - recommendation: Action to take
            """
            
            # Get AI response - executed within TEE for security
            response = self.ai_provider.generate(prompt=prompt)
            
            # Parse AI response - in production would have more robust parsing
            try:
                # Try to extract JSON from response
                response_text = response.text
                start_idx = response_text.find('{')
                end_idx = response_text.rfind('}') + 1
                
                if start_idx >= 0 and end_idx > start_idx:
                    ai_json = json.loads(response_text[start_idx:end_idx])
                    return ai_json
                else:
                    # If no JSON found, create structured response from text
                    return {
                        "security_score": 50,  # Default moderate score
                        "risk_assessment": "AI couldn't provide structured analysis. Manual review recommended.",
                        "recommendation": "Unable to automatically assess risks. Consider manual review.",
                        "raw_ai_response": response_text
                    }
            except json.JSONDecodeError:
                return {
                    "security_score": 50,  # Default moderate score
                    "risk_assessment": "AI provided unstructured response. Manual review recommended.",
                    "recommendation": "Consider manual review of transaction.",
                    "raw_ai_response": response_text
                }
                
        except Exception as e:
            self.logger.error("ai_analysis_failed", error=str(e))
            return {
                "security_score": 50,  # Default neutral score when analysis fails
                "risk_assessment": f"AI analysis encountered an error: {str(e)}",
                "recommendation": "Unable to perform AI risk assessment. Proceeding with caution."
            }
    
    def _ensure_json_serializable(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively convert a dictionary's values to ensure they're JSON serializable.
        Handles Decimal objects by converting them to float.
        
        Args:
            data: Dictionary to convert
            
        Returns:
            Dictionary with JSON serializable values
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, dict):
                result[key] = self._ensure_json_serializable(value)
            elif hasattr(value, 'to_json'):
                result[key] = value.to_json()
            elif hasattr(value, '__dict__'):
                result[key] = self._ensure_json_serializable(value.__dict__)
            else:
                # Convert Decimal and other non-serializable types to their appropriate representations
                try:
                    # Test JSON serialization
                    json.dumps(value)
                    result[key] = value
                except (TypeError, OverflowError):
                    # If it fails, convert to string or float as appropriate
                    if hasattr(value, '__float__'):
                        result[key] = float(value)
                    else:
                        result[key] = str(value)
                        
        return result
    
    def _calculate_risk_level(
        self,
        tx: Dict[str, Any],
        sender_address: str,
        simulation_result: Dict[str, Any],
        ai_analysis: Dict[str, Any],
        warnings: List[str]
    ) -> TransactionRisk:
        """
        Calculate final risk level based on all validations.
        
        Returns:
            TransactionRisk enum value
        """
        # Start with default risk level
        risk_level = TransactionRisk.LOW
        
        # Define our whitelist constants
        # WFLR contract address on Flare
        wflr_contract = "0x1d80c49bbcd1c0911346656b529df9e5c2f783d".lower()
        # Router contract address
        router_contract = "0x8a1e35f5c98c4e85b36b7b253222ee17773b2781".lower()
        
        # Ensure our safe contracts set exists and has our whitelisted contracts
        if not hasattr(self, 'known_safe_contracts'):
            self.known_safe_contracts = set()
        
        # Add these to known safe contracts
        self.known_safe_contracts.add(wflr_contract)
        self.known_safe_contracts.add(router_contract)
        
        # Get target address and ensure it's lowercase for comparison
        to_address = tx.get("to", "").lower() if tx.get("to") else ""
        
        # Check if this is a known safe contract - improved matching logic
        known_safe_contract = (
            to_address in self.known_safe_contracts or
            to_address == wflr_contract or
            to_address == router_contract
        )
        
        self.logger.info(
            "risk_assessment_details", 
            to_address=to_address,
            wflr_contract=wflr_contract,
            router_contract=router_contract,
            is_known_safe_contract=known_safe_contract,
            warning_count=len(warnings),
            ai_security_score=ai_analysis.get("security_score", 50),
            warnings=warnings,
            simulation_successful=simulation_result.get("simulation_successful", False),
            can_afford=simulation_result.get("can_afford", True),
            risk_assessment=ai_analysis.get("risk_assessment", ""),
        )
        
        # If it's a known safe contract, set to LOW risk and return immediately
        # This takes precedence over all other checks for whitelisted contracts
        if known_safe_contract:
            self.logger.info(
                "using_known_safe_contract_override", 
                to_address=to_address,
                is_wflr=(to_address == wflr_contract),
                is_router=(to_address == router_contract)
            )
            # Force LOW risk for known safe contracts regardless of other factors
            return TransactionRisk.LOW
            
        # Only proceed with other risk checks if not a known safe contract
            
        # Upgrade risk based on warnings count - be more lenient
        if len(warnings) > 5:
            risk_level = TransactionRisk.CRITICAL
            self.logger.info("risk_level_from_warnings", level="CRITICAL", count=len(warnings))
        elif len(warnings) > 3:
            risk_level = TransactionRisk.HIGH
            self.logger.info("risk_level_from_warnings", level="HIGH", count=len(warnings))
        elif len(warnings) > 1:
            risk_level = TransactionRisk.MEDIUM
            self.logger.info("risk_level_from_warnings", level="MEDIUM", count=len(warnings))
            
        # Consider simulation results
        if not simulation_result.get("simulation_successful", False):
            risk_level = TransactionRisk.HIGH
            self.logger.info("risk_level_from_simulation", level="HIGH", reason="simulation_failed")
        elif not simulation_result.get("can_afford", True):
            risk_level = TransactionRisk.HIGH
            self.logger.info("risk_level_from_simulation", level="HIGH", reason="cannot_afford")
            
        # Consider AI security score
        security_score = ai_analysis.get("security_score", 50)
        
        # Check if there was an AI analysis error (detected by our default values set during error handling)
        ai_error = "AI analysis encountered an error:" in ai_analysis.get("risk_assessment", "")
        
        # Only use the AI security score if there wasn't an analysis error
        if not ai_error:
            if security_score < 20:
                risk_level = TransactionRisk.CRITICAL
                self.logger.info("risk_level_from_ai", level="CRITICAL", score=security_score)
            elif security_score < 40:
                risk_level = max(risk_level, TransactionRisk.HIGH)
                self.logger.info("risk_level_from_ai", level="HIGH", score=security_score)
            elif security_score < 60:
                risk_level = max(risk_level, TransactionRisk.MEDIUM)
                self.logger.info("risk_level_from_ai", level="MEDIUM", score=security_score)
            elif security_score < 80:
                risk_level = max(risk_level, TransactionRisk.LOW)
                self.logger.info("risk_level_from_ai", level="LOW", score=security_score)
            else:
                # Very high security score might reduce risk level
                if risk_level == TransactionRisk.LOW:
                    risk_level = TransactionRisk.SAFE
                    self.logger.info("risk_level_from_ai", level="SAFE", score=security_score)
        else:
            self.logger.info("ai_analysis_error_detected", using_default_score=True)
        
        # Contract interactions are inherently riskier, but we've already checked for known safe contracts
        if simulation_result.get("is_contract_interaction", False) and not known_safe_contract:
            if not simulation_result.get("contract_verification", {}).get("is_verified", False):
                # Unverified contract interactions should never be SAFE
                if risk_level == TransactionRisk.SAFE:
                    risk_level = TransactionRisk.LOW
                    self.logger.info("unverified_contract_risk_adjustment", from_level="SAFE", to_level="LOW")
        
        self.logger.info("final_risk_level", level=risk_level.value)
        return risk_level
        
    def _generate_recommendation(
        self, 
        risk_level: TransactionRisk, 
        warnings: List[str],
        ai_analysis: Dict[str, Any]
    ) -> str:
        """
        Generate human-readable recommendation based on risk level.
        
        Returns:
            Recommendation string
        """
        if risk_level == TransactionRisk.CRITICAL:
            return "CRITICAL RISK DETECTED. Transaction should not proceed."
            
        if risk_level == TransactionRisk.HIGH:
            return "HIGH RISK DETECTED. Transaction should be carefully reviewed before proceeding."
            
        if risk_level == TransactionRisk.MEDIUM:
            return "MODERATE RISK DETECTED. Proceed with caution and verify transaction details."
            
        if risk_level == TransactionRisk.LOW:
            return "LOW RISK DETECTED. Transaction appears mostly safe but verify details."
            
        # SAFE
        return "Transaction appears safe to execute." 