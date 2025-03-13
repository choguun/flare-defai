"""
Smart Contract Risk Analyzer Module

This module implements comprehensive risk assessment for smart contract interactions
on the Flare network, leveraging TEE-secured Gemini AI for enhanced security analysis.
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Set, Tuple

import structlog
from web3 import Web3

from flare_defai.ai.gemini import GeminiAIProvider
from flare_defai.blockchain.explorer import BlockExplorerService

logger = structlog.get_logger(__name__)

# Known dangerous function signatures
DANGEROUS_FUNCTIONS = {
    # Self-destruct variants
    "0x41c0e1b5": "selfdestruct(address)",
    "0x9cb8a26a": "selfDestruct(address)",
    "0xa6cd9552": "destruct(address)",
    # Ownership transfers
    "0xf2fde38b": "transferOwnership(address)",
    # Access control
    "0x8da5cb5b": "owner()",
    "0x715018a6": "renounceOwnership()",
    # Proxy patterns
    "0x3659cfe6": "upgradeTo(address)",
    "0x4f1ef286": "upgradeToAndCall(address,bytes)",
    # Token approvals
    "0x095ea7b3": "approve(address,uint256)",
    "0xa22cb465": "setApprovalForAll(address,bool)",
}

# Function signature mapping
FUNCTION_SIGNATURES = {
    # ERC20
    "0xa9059cbb": "transfer(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    "0x095ea7b3": "approve(address,uint256)",
    "0x70a08231": "balanceOf(address)",
    "0x18160ddd": "totalSupply()",
    "0xdd62ed3e": "allowance(address,address)",
    # ERC721
    "0x42842e0e": "safeTransferFrom(address,address,uint256)",
    "0xb88d4fde": "safeTransferFrom(address,address,uint256,bytes)",
    "0xa22cb465": "setApprovalForAll(address,bool)",
    "0xe985e9c5": "isApprovedForAll(address,address)",
    "0x6352211e": "ownerOf(uint256)",
    # Common admin functions
    "0x8456cb59": "pause()",
    "0x3f4ba83a": "unpause()",
    # DEX functions
    "0x38ed1739": "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)",
    "0x7ff36ab5": "swapExactETHForTokens(uint256,address[],address,uint256)",
    "0x18cbafe5": "swapExactTokensForETH(uint256,uint256,address[],address,uint256)",
}

class RiskLevel(Enum):
    """Enum representing contract risk levels."""
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RiskCategory(Enum):
    """Categories of contract risks."""
    IMPLEMENTATION = "implementation"  # Code level issues
    ACCESS_CONTROL = "access_control"  # Permission issues
    UPGRADEABLE = "upgradeable"        # Contract can be changed
    EXTERNAL_CALLS = "external_calls"  # Risky external interactions
    FINANCIAL = "financial"            # Economic risks
    OPERATIONAL = "operational"        # Usage-related risks

@dataclass
class RiskFinding:
    """A specific risk finding within a contract."""
    category: RiskCategory
    level: RiskLevel
    title: str
    description: str
    locations: List[str] = field(default_factory=list)
    recommendation: Optional[str] = None

@dataclass
class ContractRiskReport:
    """Complete risk report for a smart contract."""
    contract_address: str
    chain_id: int
    risk_level: RiskLevel
    findings: List[RiskFinding] = field(default_factory=list)
    verification_status: Dict[str, Any] = field(default_factory=dict)
    bytecode_analysis: Dict[str, Any] = field(default_factory=dict)
    source_code_analysis: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    ai_analysis: Optional[Dict[str, Any]] = None
    summary: str = ""

    def add_finding(self, finding: RiskFinding) -> None:
        """Add a risk finding to the report."""
        self.findings.append(finding)
        # Update overall risk level if needed
        if finding.level.value > self.risk_level.value:
            self.risk_level = finding.level

    def get_findings_by_category(self, category: RiskCategory) -> List[RiskFinding]:
        """Get all findings in a specific category."""
        return [f for f in self.findings if f.category == category]

    def get_findings_by_level(self, level: RiskLevel) -> List[RiskFinding]:
        """Get all findings at a specific risk level."""
        return [f for f in self.findings if f.level == level]

class ContractRiskAnalyzer:
    """
    Service for analyzing smart contract risks.
    
    This service leverages:
    1. TEE-secured environment for sensitive analysis
    2. Gemini AI for advanced contract analysis
    3. Bytecode analysis for quick risk assessment
    4. Source code analysis when available
    """

    def __init__(
        self, 
        web3: Web3, 
        explorer_service: BlockExplorerService, 
        ai_provider: GeminiAIProvider
    ):
        """
        Initialize the contract risk analyzer.
        
        Args:
            web3: Initialized Web3 instance
            explorer_service: Block explorer service for fetching contract data
            ai_provider: AI provider for advanced analysis
        """
        self.web3 = web3
        self.explorer = explorer_service
        self.ai_provider = ai_provider
        self.logger = logger.bind(service="contract_risk")
        
        # Cache of analyzed contracts to prevent duplicate work
        self._contract_cache: Dict[str, ContractRiskReport] = {}
        
        # Known safe contract addresses - would be populated from trusted source
        self.known_safe_contracts: Set[str] = set()
        
    async def analyze_contract(
        self, 
        contract_address: str,
        force_refresh: bool = False
    ) -> ContractRiskReport:
        """
        Perform comprehensive risk analysis on a smart contract.
        
        Args:
            contract_address: The address of the contract to analyze
            force_refresh: Whether to ignore cache and re-analyze
            
        Returns:
            Complete risk analysis report
        """
        # Normalize address
        contract_address = self.web3.to_checksum_address(contract_address)
        
        # Check cache first unless refresh requested
        if not force_refresh and contract_address in self._contract_cache:
            return self._contract_cache[contract_address]
            
        self.logger.info("analyzing_contract", address=contract_address)
        
        # Start with a default report
        report = ContractRiskReport(
            contract_address=contract_address,
            chain_id=self.web3.eth.chain_id,
            risk_level=RiskLevel.LOW,  # Default starting level
        )
        
        # Check if it's actually a contract
        code = self.web3.eth.get_code(contract_address)
        if not code or len(code) <= 2:  # Just '0x' means not a contract
            report.risk_level = RiskLevel.CRITICAL
            report.add_finding(RiskFinding(
                category=RiskCategory.IMPLEMENTATION,
                level=RiskLevel.CRITICAL,
                title="Not a Contract",
                description="The address does not contain contract code. It might be an EOA or a self-destructed contract.",
                recommendation="Do not interact with this address as a contract.",
            ))
            report.summary = "CRITICAL RISK: Not a valid smart contract."
            self._contract_cache[contract_address] = report
            return report
            
        # Check known safe contracts
        if contract_address in self.known_safe_contracts:
            report.risk_level = RiskLevel.SAFE
            report.verification_status["is_verified"] = True
            report.verification_status["is_trusted"] = True
            report.summary = "This contract is verified and marked as trusted."
            self._contract_cache[contract_address] = report
            return report
        
        # Fetch verification status from explorer
        try:
            verification_data = await self.explorer.get_contract_verification(contract_address)
            report.verification_status = verification_data
        except Exception as e:
            self.logger.warning("failed_to_get_verification", error=str(e))
            report.verification_status = {
                "is_verified": False,
                "error": str(e)
            }
        
        # If contract is not verified, increase risk level
        if not report.verification_status.get("is_verified", False):
            report.risk_level = RiskLevel.MEDIUM
            report.add_finding(RiskFinding(
                category=RiskCategory.IMPLEMENTATION,
                level=RiskLevel.MEDIUM,
                title="Unverified Contract",
                description="The contract source code is not verified on block explorer.",
                recommendation="Exercise caution when interacting with unverified contracts.",
            ))
        
        # Analyze bytecode for dangerous patterns - runs in TEE for security
        bytecode_findings = self._analyze_bytecode(contract_address, code)
        report.bytecode_analysis = {
            "dangerous_functions": bytecode_findings[0],
            "selfdestruct_found": bytecode_findings[1],
            "delegatecall_found": bytecode_findings[2],
            "is_proxy": bytecode_findings[3],
        }
        
        # Add bytecode-based findings to report
        for function_sig, function_name in bytecode_findings[0].items():
            report.add_finding(RiskFinding(
                category=RiskCategory.IMPLEMENTATION,
                level=RiskLevel.HIGH,
                title=f"Dangerous Function: {function_name}",
                description=f"The contract contains potentially dangerous function {function_name}.",
                locations=[f"Function signature: {function_sig}"],
                recommendation="Review how and when this function can be called."
            ))
            
        if bytecode_findings[1]:
            report.add_finding(RiskFinding(
                category=RiskCategory.IMPLEMENTATION,
                level=RiskLevel.HIGH,
                title="Self-Destruct Found",
                description="The contract contains code that can self-destruct, potentially locking funds forever.",
                recommendation="Verify the conditions under which self-destruct can be triggered."
            ))
            
        if bytecode_findings[2]:
            report.add_finding(RiskFinding(
                category=RiskCategory.EXTERNAL_CALLS,
                level=RiskLevel.MEDIUM,
                title="Delegatecall Usage",
                description="The contract uses delegatecall which can be dangerous if not properly secured.",
                recommendation="Ensure delegatecall targets are trusted and cannot be manipulated."
            ))
            
        if bytecode_findings[3]:
            report.add_finding(RiskFinding(
                category=RiskCategory.UPGRADEABLE,
                level=RiskLevel.MEDIUM,
                title="Proxy Pattern Detected",
                description="This appears to be a proxy contract that delegates to another implementation.",
                recommendation="Review the upgrade mechanism and implementation contract."
            ))
        
        # Fetch and analyze source code if available
        if report.verification_status.get("is_verified", False):
            try:
                source_code = await self.explorer.get_contract_source(contract_address)
                source_analysis = self._analyze_source_code(source_code)
                report.source_code_analysis = source_analysis
                
                # Add findings from source code analysis
                if source_analysis.get("upgradeability_risk", False):
                    report.add_finding(RiskFinding(
                        category=RiskCategory.UPGRADEABLE,
                        level=RiskLevel.MEDIUM,
                        title="Upgradeable Contract",
                        description="This contract can be upgraded, potentially changing its behavior in the future.",
                        recommendation="Monitor upgrade events and admin operations on this contract."
                    ))
                    
                if source_analysis.get("centralized_ownership", False):
                    report.add_finding(RiskFinding(
                        category=RiskCategory.ACCESS_CONTROL,
                        level=RiskLevel.MEDIUM,
                        title="Centralized Control",
                        description="The contract has centralized control through owner/admin functions.",
                        recommendation="Verify the trustworthiness of the contract owner/admin."
                    ))
                    
                # Check for access control issues
                for issue in source_analysis.get("access_control_issues", []):
                    report.add_finding(RiskFinding(
                        category=RiskCategory.ACCESS_CONTROL,
                        level=RiskLevel.MEDIUM,
                        title=issue["title"],
                        description=issue["description"],
                        locations=issue.get("locations", []),
                        recommendation=issue.get("recommendation")
                    ))
                    
            except Exception as e:
                self.logger.warning("source_code_analysis_failed", error=str(e))
                report.source_code_analysis = {
                    "error": str(e)
                }
                
        # Perform AI analysis - runs in TEE for security
        ai_analysis = await self._perform_ai_analysis(
            contract_address, 
            report.bytecode_analysis,
            report.source_code_analysis if hasattr(report, "source_code_analysis") else None
        )
        report.ai_analysis = ai_analysis
        
        # Add AI-generated findings
        if ai_analysis and "findings" in ai_analysis:
            for finding in ai_analysis["findings"]:
                try:
                    category = RiskCategory(finding.get("category", "implementation"))
                except ValueError:
                    category = RiskCategory.IMPLEMENTATION
                    
                try:
                    level = RiskLevel(finding.get("risk_level", "medium"))
                except ValueError:
                    level = RiskLevel.MEDIUM
                    
                report.add_finding(RiskFinding(
                    category=category,
                    level=level,
                    title=finding.get("title", "AI-detected Issue"),
                    description=finding.get("description", "No description provided"),
                    recommendation=finding.get("recommendation")
                ))
                
        # Calculate overall risk level based on findings
        if len(report.get_findings_by_level(RiskLevel.CRITICAL)) > 0:
            report.risk_level = RiskLevel.CRITICAL
        elif len(report.get_findings_by_level(RiskLevel.HIGH)) > 0:
            report.risk_level = RiskLevel.HIGH
        elif len(report.get_findings_by_level(RiskLevel.MEDIUM)) > 0:
            report.risk_level = RiskLevel.MEDIUM
        elif len(report.get_findings_by_level(RiskLevel.LOW)) > 0:
            report.risk_level = RiskLevel.LOW
        else:
            report.risk_level = RiskLevel.SAFE
            
        # Generate summary
        report.summary = self._generate_summary(report)
        
        # Cache result
        self._contract_cache[contract_address] = report
        
        return report
        
    def _analyze_bytecode(
        self, 
        contract_address: str, 
        bytecode: bytes
    ) -> Tuple[Dict[str, str], bool, bool, bool]:
        """
        Analyze contract bytecode for risky patterns.
        
        Args:
            contract_address: Address of the contract
            bytecode: Raw bytecode of the contract
            
        Returns:
            Tuple of (dangerous functions, has selfdestruct, has delegatecall, is proxy)
        """
        # Convert to hex string if not already
        if not isinstance(bytecode, str):
            bytecode_hex = bytecode.hex()
            if not bytecode_hex.startswith("0x"):
                bytecode_hex = "0x" + bytecode_hex
        else:
            bytecode_hex = bytecode
            
        # Check for dangerous function signatures
        dangerous_functions = {}
        for signature, name in DANGEROUS_FUNCTIONS.items():
            if signature in bytecode_hex:
                dangerous_functions[signature] = name
                
        # Check for selfdestruct opcode (FF)
        has_selfdestruct = bool(re.search(r"ff(?:[0-9a-f]{2}){0,32}(?:50|f3)", bytecode_hex, re.IGNORECASE))
        
        # Check for delegatecall opcode (F4)
        has_delegatecall = bool(re.search(r"f4(?:[0-9a-f]{2}){0,32}(?:50|f3)", bytecode_hex, re.IGNORECASE))
        
        # Proxy contract detection - simplified heuristic
        # Looking for minimal code that uses delegatecall
        is_proxy = has_delegatecall and len(bytecode_hex) < 1000
        
        return (dangerous_functions, has_selfdestruct, has_delegatecall, is_proxy)
    
    def _analyze_source_code(self, source_code: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze contract source code for risks.
        
        Args:
            source_code: Source code and metadata
            
        Returns:
            Analysis results
        """
        # This would be a more complex analysis in production
        # Here we'll implement a simplified version
        
        result = {
            "upgradeability_risk": False,
            "centralized_ownership": False,
            "access_control_issues": [],
            "timestamp_dependency": False,
        }
        
        # Simple pattern matching for known risky patterns
        code_str = json.dumps(source_code)  # Quick way to search all nested content
        
        # Check for upgradeability
        if any(pattern in code_str for pattern in [
            "Proxy", "delegatecall", "upgradeTo", "upgradeToAndCall", "implementation()", 
            "Upgradeable", "ERC1967", "TransparentUpgradeableProxy"
        ]):
            result["upgradeability_risk"] = True
            
        # Check for centralized ownership
        if any(pattern in code_str for pattern in [
            "onlyOwner", "onlyAdmin", "Ownable", "owner()", "transferOwnership", 
            "Access", "auth", "authorize", "isAuthorized"
        ]):
            result["centralized_ownership"] = True
            
        # Check for timestamp dependency
        if any(pattern in code_str for pattern in [
            "block.timestamp", "now", "block.number"
        ]):
            result["timestamp_dependency"] = True
            
        # In a real implementation, we would parse the AST and do much more thorough analysis
            
        return result
    
    async def _perform_ai_analysis(
        self, 
        contract_address: str,
        bytecode_analysis: Dict[str, Any],
        source_analysis: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Use Gemini AI to perform advanced contract analysis.
        
        Args:
            contract_address: Address of the contract
            bytecode_analysis: Results from bytecode analysis
            source_analysis: Results from source analysis (if available)
            
        Returns:
            AI analysis results
        """
        try:
            # Prepare data for AI analysis
            analysis_data = {
                "contract_address": contract_address,
                "chain_id": self.web3.eth.chain_id,
                "bytecode_analysis": bytecode_analysis,
            }
            
            if source_analysis:
                analysis_data["source_analysis"] = source_analysis
                
            # Format prompt for Gemini AI
            prompt = f"""
            Analyze this smart contract for security risks:
            
            {json.dumps(analysis_data, indent=2)}
            
            Focus on:
            1. Is this a known malicious pattern?
            2. Are there dangerous functions that could risk user funds?
            3. Is the contract upgradeable and if so, what are the risks?
            4. Are there centralized control risks?
            5. What access control issues might be present?
            
            Provide a JSON response with:
            - security_score: 0-100 (higher is safer)
            - risk_assessment: Short description of overall risk
            - findings: List of specific issues found, each with:
              * title: Brief name of the issue
              * category: One of [implementation, access_control, upgradeable, external_calls, financial, operational]
              * risk_level: One of [safe, low, medium, high, critical]
              * description: Detailed explanation
              * recommendation: How to mitigate the risk
            """
            
            # Get AI response - executed within TEE for security
            response = await self.ai_provider.generate_text(prompt)
            
            # Parse AI response - in production would have more robust parsing
            try:
                # Try to extract JSON from response
                start_idx = response.find('{')
                end_idx = response.rfind('}') + 1
                
                if start_idx >= 0 and end_idx > start_idx:
                    ai_json = json.loads(response[start_idx:end_idx])
                    return ai_json
                else:
                    # If no JSON found, create structured response from text
                    return {
                        "security_score": 50,  # Default moderate score
                        "risk_assessment": "AI couldn't provide structured analysis. Manual review recommended.",
                        "findings": [
                            {
                                "title": "AI Analysis Incomplete",
                                "category": "implementation",
                                "risk_level": "medium", 
                                "description": "The AI couldn't provide a structured analysis of this contract.",
                                "recommendation": "Perform manual code review."
                            }
                        ],
                        "raw_ai_response": response
                    }
            except json.JSONDecodeError:
                return {
                    "security_score": 50,  # Default moderate score
                    "risk_assessment": "AI provided unstructured response. Manual review recommended.",
                    "findings": [
                        {
                            "title": "AI Analysis Error",
                            "category": "implementation",
                            "risk_level": "medium",
                            "description": "The AI response couldn't be parsed into structured data.",
                            "recommendation": "Perform manual code review."
                        }
                    ],
                    "raw_ai_response": response
                }
                
        except Exception as e:
            self.logger.error("ai_analysis_failed", error=str(e))
            return {
                "security_score": 0,
                "risk_assessment": f"AI analysis failed: {str(e)}",
                "findings": [
                    {
                        "title": "AI Analysis Failed",
                        "category": "operational",
                        "risk_level": "medium",
                        "description": f"Error during AI analysis: {str(e)}",
                        "recommendation": "Retry analysis or perform manual review."
                    }
                ]
            }
    
    def _generate_summary(self, report: ContractRiskReport) -> str:
        """Generate a human-readable summary of the risk report."""
        critical_count = len(report.get_findings_by_level(RiskLevel.CRITICAL))
        high_count = len(report.get_findings_by_level(RiskLevel.HIGH))
        medium_count = len(report.get_findings_by_level(RiskLevel.MEDIUM))
        low_count = len(report.get_findings_by_level(RiskLevel.LOW))
        
        if critical_count > 0:
            return f"CRITICAL RISK: Found {critical_count} critical, {high_count} high, and {medium_count} medium issues. DO NOT interact with this contract."
            
        if high_count > 0:
            return f"HIGH RISK: Found {high_count} high and {medium_count} medium security issues. Proceed with extreme caution."
            
        if medium_count > 0:
            return f"MEDIUM RISK: Found {medium_count} medium and {low_count} low security issues. Review findings before proceeding."
            
        if low_count > 0:
            return f"LOW RISK: Found {low_count} minor security considerations. Contract appears relatively safe."
            
        return "Contract appears safe based on our analysis. No security issues detected."
    
    async def assess_transaction_risk(
        self, 
        tx: Dict[str, Any],
        sender_address: str
    ) -> Dict[str, Any]:
        """
        Assess risk of a transaction, especially for contract interactions.
        
        Args:
            tx: Transaction to assess
            sender_address: Address of transaction sender
            
        Returns:
            Risk assessment report for the transaction
        """
        # Skip contract risk assessment for non-contract interactions
        if not tx.get("to"):
            return {
                "risk_level": "medium",
                "reason": "Contract creation transaction",
                "recommendation": "Review the contract code being deployed."
            }
            
        to_address = tx.get("to")
        
        # Check if target is a contract
        code = self.web3.eth.get_code(to_address)
        if not code or len(code) <= 2:  # Just '0x' means not a contract
            return {
                "risk_level": "low",
                "reason": "Regular address (not a contract)",
                "recommendation": "Verify the recipient address is correct."
            }
            
        # For contract interactions, perform full contract analysis
        contract_report = await self.analyze_contract(to_address)
        
        # Decode function being called if data is present
        function_info = "Unknown function"
        if tx.get("data") and len(tx.get("data")) >= 10:
            function_sig = tx.get("data")[:10]
            # Look up function name
            if function_sig in FUNCTION_SIGNATURES:
                function_info = FUNCTION_SIGNATURES[function_sig]
            elif function_sig in DANGEROUS_FUNCTIONS:
                function_info = DANGEROUS_FUNCTIONS[function_sig]
                
        # Prepare transaction-specific assessment
        return {
            "risk_level": contract_report.risk_level.value,
            "contract_analysis": {
                "address": to_address,
                "verification_status": contract_report.verification_status,
                "overall_risk": contract_report.risk_level.value,
                "critical_findings_count": len(contract_report.get_findings_by_level(RiskLevel.CRITICAL)),
                "high_findings_count": len(contract_report.get_findings_by_level(RiskLevel.HIGH)),
                "medium_findings_count": len(contract_report.get_findings_by_level(RiskLevel.MEDIUM)),
            },
            "function_info": function_info,
            "summary": contract_report.summary,
            "recommendation": (
                "Do not proceed with this transaction." 
                if contract_report.risk_level in [RiskLevel.CRITICAL, RiskLevel.HIGH]
                else "Review risks carefully before proceeding."
            )
        } 