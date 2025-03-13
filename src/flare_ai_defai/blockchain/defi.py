"""
DeFi Module

This module implements decentralized finance operations on the Flare network,
including token swaps through Uniswap-compatible protocols.
"""

import json
from typing import Any
from decimal import Decimal

import structlog
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError

logger = structlog.get_logger(__name__)

# ABI definitions
UNISWAP_V2_ROUTER_ABI = json.loads('''
[
  {
    "inputs": [
      {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
      {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
      {"internalType": "address[]", "name": "path", "type": "address[]"},
      {"internalType": "address", "name": "to", "type": "address"},
      {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "swapExactTokensForTokens",
    "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "inputs": [
      {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
      {"internalType": "address[]", "name": "path", "type": "address[]"},
      {"internalType": "address", "name": "to", "type": "address"},
      {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "swapExactETHForTokens",
    "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
    "stateMutability": "payable",
    "type": "function"
  },
  {
    "inputs": [
      {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
      {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
      {"internalType": "address[]", "name": "path", "type": "address[]"},
      {"internalType": "address", "name": "to", "type": "address"},
      {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "swapExactTokensForETH",
    "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
    "stateMutability": "nonpayable",
    "type": "function"
  }
]
''')

UNISWAP_V3_ROUTER_ABI = json.loads('''
[
  {
    "inputs": [
      {
        "components": [
          {"internalType": "address", "name": "tokenIn", "type": "address"},
          {"internalType": "address", "name": "tokenOut", "type": "address"},
          {"internalType": "uint24", "name": "fee", "type": "uint24"},
          {"internalType": "address", "name": "recipient", "type": "address"},
          {"internalType": "uint256", "name": "deadline", "type": "uint256"},
          {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
          {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"},
          {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
        ],
        "internalType": "struct ISwapRouter.ExactInputSingleParams",
        "name": "params",
        "type": "tuple"
      }
    ],
    "name": "exactInputSingle",
    "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "inputs": [
      {
        "components": [
          {"internalType": "bytes", "name": "path", "type": "bytes"},
          {"internalType": "address", "name": "recipient", "type": "address"},
          {"internalType": "uint256", "name": "deadline", "type": "uint256"},
          {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
          {"internalType": "uint256", "name": "amountOutMinimum", "type": "uint256"}
        ],
        "internalType": "struct ISwapRouter.ExactInputParams",
        "name": "params",
        "type": "tuple"
      }
    ],
    "name": "exactInput",
    "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
    "stateMutability": "nonpayable",
    "type": "function"
  }
]
''')

ERC20_ABI = json.loads('''
[
  {
    "inputs": [
      {"internalType": "address", "name": "spender", "type": "address"},
      {"internalType": "uint256", "name": "amount", "type": "uint256"}
    ],
    "name": "approve",
    "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function"
  }
]
''')

# Common token addresses for Flare/Coston2 network 
# In a production app, these would typically come from a configuration file or database
TOKEN_ADDRESSES = {
    "FLR": "0x1111111111111111111111111111111111111111",  # Native token, placeholder address
    "WFLR": "0x1D80c49BbBCd1C0911346656B529DF9E5c2F783d",  # Wrapped FLR
    "USDC": "0xeCF51Ee929f4886dD9d41A703d88c3Aa1D777455",
    "USDT": "0x8aE0EeedD35DbEFed8C4903e31A4Ab8d6991A4e2",
    "WETH": "0xaCB447D8dD750752075275EF907362e825fDBa10",
    "sFLR": "0x02f0826ef6aD107Cfc861152B32B52fD11BaB9ED"
}

# Router contracts for Flare/Coston2
UNISWAP_V2_ROUTER = "0xF4943f2dEc7E4914216FCc88ee07FE4E16F14377"  # Example V2 router
UNISWAP_V3_ROUTER = "0x28239F8e7Dc9A8773291404Bcb7995a41b37b56B"  # Example V3 router

# Default slippage tolerance and deadline
DEFAULT_SLIPPAGE = Decimal("0.005")  # 0.5%
DEFAULT_DEADLINE = 20 * 60  # 20 minutes in seconds


class DeFiService:
    """
    Service for executing decentralized finance operations on Flare network
    """
    
    def __init__(self, web3: Web3) -> None:
        """
        Initialize the DeFi service.
        
        Args:
            web3: Initialized Web3 instance
        """
        self.web3 = web3
        self.logger = logger.bind(service="defi")
        
        # Initialize contract instances
        self.v2_router = self.web3.eth.contract(
            address=self.web3.to_checksum_address(UNISWAP_V2_ROUTER),
            abi=UNISWAP_V2_ROUTER_ABI
        )
        
        self.v3_router = self.web3.eth.contract(
            address=self.web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=UNISWAP_V3_ROUTER_ABI
        )
        
        # Map token symbols to addresses
        self.token_addresses = TOKEN_ADDRESSES
    
    def _get_token_contract(self, token_address: str) -> Contract:
        """Get a contract instance for an ERC20 token."""
        return self.web3.eth.contract(
            address=self.web3.to_checksum_address(token_address),
            abi=ERC20_ABI
        )
    
    def _approve_token_if_needed(self, token_address: str, spender: str, amount: int, sender: str) -> dict[str, Any] | None:
        """
        Approve token spending if needed.
        
        Args:
            token_address: Address of the token to approve
            spender: Address of the spender (router)
            amount: Amount to approve (in wei)
            sender: Address of the sender
            
        Returns:
            Transaction dictionary if approval needed, None otherwise
        """
        # Skip approval for native token
        if token_address.lower() == self.token_addresses["FLR"].lower():
            return None
            
        token_contract = self._get_token_contract(token_address)
        
        # Check if approval is needed
        # In production, would check current allowance first
        
        # Build approval transaction
        tx = {
            'from': sender,
            'to': token_address,
            'gas': 100000,  # Estimate gas in production
            'gasPrice': self.web3.eth.gas_price,
            'nonce': self.web3.eth.get_transaction_count(sender),
            'data': token_contract.encodeABI(
                fn_name='approve',
                args=[spender, amount]
            )
        }
        
        self.logger.info("token_approval", token=token_address, spender=spender, amount=amount)
        return tx
    
    def create_v2_swap_tx(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        sender: str,
        slippage: Decimal = DEFAULT_SLIPPAGE
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """
        Create transaction for swapping tokens using Uniswap V2.
        
        Args:
            from_token: Symbol of the token to swap from
            to_token: Symbol of the token to swap to
            amount: Amount to swap in original units (not wei)
            sender: Address of the sender
            slippage: Maximum acceptable slippage
            
        Returns:
            Tuple of (swap transaction, approval transaction if needed)
        """
        self.logger.info(
            "creating_v2_swap",
            from_token=from_token,
            to_token=to_token,
            amount=amount,
            sender=sender
        )
        
        # Get token addresses
        from_token_address = self.token_addresses.get(from_token.upper())
        to_token_address = self.token_addresses.get(to_token.upper())
        
        if not from_token_address or not to_token_address:
            raise ValueError(f"Unknown token: {from_token if not from_token_address else to_token}")
        
        # Handle native token (FLR)
        is_exact_eth_for_tokens = from_token.upper() == "FLR"
        is_exact_tokens_for_eth = to_token.upper() == "FLR"
        
        # Convert amount to wei
        amount_in_wei = self.web3.to_wei(amount, 'ether')
        
        # Calculate min amount out with slippage
        # In production, would query price first for better estimation
        amount_out_min = int(amount_in_wei * (1 - slippage))
        
        # Set deadline
        deadline = self.web3.eth.get_block('latest').timestamp + DEFAULT_DEADLINE
        
        # Determine the swap path
        if is_exact_eth_for_tokens:
            path = [self.token_addresses["WFLR"], to_token_address]
            fn_name = 'swapExactETHForTokens'
            value = amount_in_wei
            args = [amount_out_min, path, sender, deadline]
        elif is_exact_tokens_for_eth:
            path = [from_token_address, self.token_addresses["WFLR"]]
            fn_name = 'swapExactTokensForETH'
            value = 0
            args = [amount_in_wei, amount_out_min, path, sender, deadline]
        else:
            path = [from_token_address, to_token_address]
            fn_name = 'swapExactTokensForTokens'
            value = 0
            args = [amount_in_wei, amount_out_min, path, sender, deadline]
        
        # Create swap transaction
        swap_tx = {
            'from': sender,
            'to': self.v2_router.address,
            'gas': 300000,  # Estimate gas in production
            'gasPrice': self.web3.eth.gas_price,
            'nonce': self.web3.eth.get_transaction_count(sender),
            'value': value,
            'data': self.v2_router.encodeABI(fn_name=fn_name, args=args)
        }
        
        # Create approval transaction if needed
        approval_tx = None
        if not is_exact_eth_for_tokens:
            approval_tx = self._approve_token_if_needed(
                from_token_address,
                self.v2_router.address,
                amount_in_wei,
                sender
            )
        
        return swap_tx, approval_tx
    
    def create_v3_swap_tx(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        sender: str,
        fee_tier: int = 3000,  # 0.3% fee tier
        slippage: Decimal = DEFAULT_SLIPPAGE
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """
        Create transaction for swapping tokens using Uniswap V3.
        
        Args:
            from_token: Symbol of the token to swap from
            to_token: Symbol of the token to swap to
            amount: Amount to swap in original units (not wei)
            sender: Address of the sender
            fee_tier: Fee tier (500, 3000, 10000)
            slippage: Maximum acceptable slippage
            
        Returns:
            Tuple of (swap transaction, approval transaction if needed)
        """
        self.logger.info(
            "creating_v3_swap",
            from_token=from_token,
            to_token=to_token,
            amount=amount,
            sender=sender,
            fee_tier=fee_tier
        )
        
        # Get token addresses
        from_token_address = self.token_addresses.get(from_token.upper())
        to_token_address = self.token_addresses.get(to_token.upper())
        
        if not from_token_address or not to_token_address:
            raise ValueError(f"Unknown token: {from_token if not from_token_address else to_token}")
        
        # Convert amount to wei
        amount_in_wei = self.web3.to_wei(amount, 'ether')
        
        # Calculate min amount out with slippage
        # In production, would query price first for better estimation
        amount_out_min = int(amount_in_wei * (1 - slippage))
        
        # Set deadline
        deadline = self.web3.eth.get_block('latest').timestamp + DEFAULT_DEADLINE
        
        # Create params for exactInputSingle
        params = {
            'tokenIn': from_token_address,
            'tokenOut': to_token_address,
            'fee': fee_tier,
            'recipient': sender,
            'deadline': deadline,
            'amountIn': amount_in_wei,
            'amountOutMinimum': amount_out_min,
            'sqrtPriceLimitX96': 0  # No price limit
        }
        
        # Create swap transaction
        swap_tx = {
            'from': sender,
            'to': self.v3_router.address,
            'gas': 300000,  # Estimate gas in production
            'gasPrice': self.web3.eth.gas_price,
            'nonce': self.web3.eth.get_transaction_count(sender),
            'value': amount_in_wei if from_token.upper() == "FLR" else 0,
            'data': self.v3_router.encodeABI(fn_name='exactInputSingle', args=[params])
        }
        
        # Create approval transaction if needed
        approval_tx = None
        if from_token.upper() != "FLR":
            approval_tx = self._approve_token_if_needed(
                from_token_address,
                self.v3_router.address,
                amount_in_wei,
                sender
            )
        
        return swap_tx, approval_tx
    
    def create_swap_tx(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        sender: str,
        use_v3: bool = True
    ) -> dict[str, Any]:
        """
        Create a transaction for swapping tokens, choosing between V2 and V3.
        
        Args:
            from_token: Symbol of the token to swap from
            to_token: Symbol of the token to swap to
            amount: Amount to swap (in token units, not wei)
            sender: Address of the sender
            use_v3: Whether to use V3 or V2
            
        Returns:
            Transaction dictionary
        """
        if use_v3:
            swap_tx, approval_tx = self.create_v3_swap_tx(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                sender=sender
            )
        else:
            swap_tx, approval_tx = self.create_v2_swap_tx(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                sender=sender
            )
        
        # If approval is needed, we should handle it separately
        # For this implementation, we just return the swap transaction
        # In a full implementation, we would need to wait for approval confirmation
        # before executing the swap
        
        return swap_tx
