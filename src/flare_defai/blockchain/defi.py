"""
DeFi Module

This module implements decentralized finance operations on the Flare network,
including token swaps through Uniswap-compatible protocols.

Integration with SparkDEX (V2 & V3.1 DEX):
- Supports token swaps via V2 and V3 routers
- Supports liquidity provision for token pairs
- Uses verified contract addresses from FlareScan (https://flarescan.com)
"""

import json
import time
from decimal import Decimal
from typing import Any

import structlog
from web3 import Web3
from web3.contract import Contract
from web3.middleware import ExtraDataToPOAMiddleware

logger = structlog.get_logger(__name__)

# ABI definitions
UNISWAP_V2_ROUTER_ABI = json.loads("""
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
  },
  {
    "inputs": [
      {"internalType": "address", "name": "tokenA", "type": "address"},
      {"internalType": "address", "name": "tokenB", "type": "address"},
      {"internalType": "uint256", "name": "amountADesired", "type": "uint256"},
      {"internalType": "uint256", "name": "amountBDesired", "type": "uint256"},
      {"internalType": "uint256", "name": "amountAMin", "type": "uint256"},
      {"internalType": "uint256", "name": "amountBMin", "type": "uint256"},
      {"internalType": "address", "name": "to", "type": "address"},
      {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "addLiquidity",
    "outputs": [
      {"internalType": "uint256", "name": "amountA", "type": "uint256"},
      {"internalType": "uint256", "name": "amountB", "type": "uint256"},
      {"internalType": "uint256", "name": "liquidity", "type": "uint256"}
    ],
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "inputs": [
      {"internalType": "address", "name": "token", "type": "address"},
      {"internalType": "uint256", "name": "amountTokenDesired", "type": "uint256"},
      {"internalType": "uint256", "name": "amountTokenMin", "type": "uint256"},
      {"internalType": "uint256", "name": "amountETHMin", "type": "uint256"},
      {"internalType": "address", "name": "to", "type": "address"},
      {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "addLiquidityETH",
    "outputs": [
      {"internalType": "uint256", "name": "amountToken", "type": "uint256"},
      {"internalType": "uint256", "name": "amountETH", "type": "uint256"},
      {"internalType": "uint256", "name": "liquidity", "type": "uint256"}
    ],
    "stateMutability": "payable",
    "type": "function"
  }
]
""")

UNISWAP_V3_ROUTER_ABI = json.loads("""
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
""")

# Adding Uniswap V3 Position Manager ABI for liquidity management
UNISWAP_V3_NFT_MANAGER_ABI = json.loads("""
[
  {
    "inputs": [
      {
        "components": [
          {"internalType": "address", "name": "token0", "type": "address"},
          {"internalType": "address", "name": "token1", "type": "address"},
          {"internalType": "uint24", "name": "fee", "type": "uint24"},
          {"internalType": "int24", "name": "tickLower", "type": "int24"},
          {"internalType": "int24", "name": "tickUpper", "type": "int24"},
          {"internalType": "uint256", "name": "amount0Desired", "type": "uint256"},
          {"internalType": "uint256", "name": "amount1Desired", "type": "uint256"},
          {"internalType": "uint256", "name": "amount0Min", "type": "uint256"},
          {"internalType": "uint256", "name": "amount1Min", "type": "uint256"},
          {"internalType": "address", "name": "recipient", "type": "address"},
          {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "internalType": "struct INonfungiblePositionManager.MintParams",
        "name": "params",
        "type": "tuple"
      }
    ],
    "name": "mint",
    "outputs": [
      {"internalType": "uint256", "name": "tokenId", "type": "uint256"},
      {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
      {"internalType": "uint256", "name": "amount0", "type": "uint256"},
      {"internalType": "uint256", "name": "amount1", "type": "uint256"}
    ],
    "stateMutability": "payable",
    "type": "function"
  }
]
""")

# ABI for Wrapped FLR (WFLR)
WFLR_ABI = json.loads("""
[
  {
    "constant": true,
    "inputs": [],
    "name": "name",
    "outputs": [{"name": "", "type": "string"}],
    "payable": false,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": false,
    "inputs": [{"name": "guy", "type": "address"}, {"name": "wad", "type": "uint256"}],
    "name": "approve",
    "outputs": [{"name": "", "type": "bool"}],
    "payable": false,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": true,
    "inputs": [],
    "name": "totalSupply",
    "outputs": [{"name": "", "type": "uint256"}],
    "payable": false,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": false,
    "inputs": [{"name": "src", "type": "address"}, {"name": "dst", "type": "address"}, {"name": "wad", "type": "uint256"}],
    "name": "transferFrom",
    "outputs": [{"name": "", "type": "bool"}],
    "payable": false,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": false,
    "inputs": [{"name": "wad", "type": "uint256"}],
    "name": "withdraw",
    "outputs": [],
    "payable": false,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": true,
    "inputs": [],
    "name": "decimals",
    "outputs": [{"name": "", "type": "uint8"}],
    "payable": false,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": true,
    "inputs": [{"name": "account", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "", "type": "uint256"}],
    "payable": false,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": true,
    "inputs": [],
    "name": "symbol",
    "outputs": [{"name": "", "type": "string"}],
    "payable": false,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "constant": false,
    "inputs": [{"name": "dst", "type": "address"}, {"name": "wad", "type": "uint256"}],
    "name": "transfer",
    "outputs": [{"name": "", "type": "bool"}],
    "payable": false,
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "constant": false,
    "inputs": [],
    "name": "deposit",
    "outputs": [],
    "payable": true,
    "stateMutability": "payable",
    "type": "function"
  },
  {
    "constant": true,
    "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
    "name": "allowance",
    "outputs": [{"name": "", "type": "uint256"}],
    "payable": false,
    "stateMutability": "view",
    "type": "function"
  },
  {
    "payable": true,
    "stateMutability": "payable",
    "type": "fallback"
  },
  {
    "anonymous": false,
    "inputs": [{"indexed": true, "name": "src", "type": "address"}, {"indexed": true, "name": "guy", "type": "address"}, {"indexed": false, "name": "wad", "type": "uint256"}],
    "name": "Approval",
    "type": "event"
  },
  {
    "anonymous": false,
    "inputs": [{"indexed": true, "name": "src", "type": "address"}, {"indexed": true, "name": "dst", "type": "address"}, {"indexed": false, "name": "wad", "type": "uint256"}],
    "name": "Transfer",
    "type": "event"
  },
  {
    "anonymous": false,
    "inputs": [{"indexed": true, "name": "dst", "type": "address"}, {"indexed": false, "name": "wad", "type": "uint256"}],
    "name": "Deposit",
    "type": "event"
  },
  {
    "anonymous": false,
    "inputs": [{"indexed": true, "name": "src", "type": "address"}, {"indexed": false, "name": "wad", "type": "uint256"}],
    "name": "Withdrawal",
    "type": "event"
  }
]
""")

ERC20_ABI = json.loads("""
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
""")

# Common token addresses for Mainnet network
# In a production app, these would typically come from a configuration file or database
TOKEN_ADDRESSES = {
    "FLR": "0x1111111111111111111111111111111111111111",  # Native token, placeholder address
    "WFLR": "0x1D80c49BbBCd1C0911346656B529DF9E5c2F783d",  # Wrapped FLR
    "USDC": "0xFbDa5F676cB37624f28265A144A48B0d6e87d3b6",
}

# Router contracts for SparkDEX on Flare network
# Addresses verified on https://flarescan.com
V2_FACTORY = "0x16b619B04c961E8f4F06C10B42FDAbb328980A89"
UNISWAP_V2_ROUTER = "0x4a1E5A90e9943467FAd1acea1E7F0e5e88472a1e"  # SparkDEX UniswapV2Router02
UNISWAP_V3_ROUTER = "0x8a1E35F5c98C4E85B36B7B253222eE17773b2781"  # SparkDEX SwapRouter
V3_FACTORY = "0x8A2578d23d4C532cC9A98FaD91C0523f5efDE652"
UNIVERSAL_ROUTER = "0x0f3D8a38D4c74afBebc2c42695642f0e3acb15D3"
UNISWAP_V3_POSITION_MANAGER = "0xEE5FF5Bc5F852764b5584d92A4d592A53DC527da"  # SparkDEX NonfungiblePositionManager

# Additional SparkDEX contracts
V3_MIGRATOR = "0xf2f986C04387570A7C7819fac51bd553bb0814af"
TOKEN_DISTRIBUTOR = "0x30FAA249e1ec3e75e203feBD35eb010b8E7BD22B"
UNSUPPORTED = "0x38D411c8bBA193C8C8393DAAcEa67F9d9105EFB7"
QUOTER_V2 = "0x5B5513c55fd06e2658010c121c37b07fC8e8B705"
PERMIT2 = "0xB952578f3520EE8Ea45b7914994dcf4702cEe578"
NFT_DESCRIPTOR = "0x840777EF3ED0457729354754946D96c07116651e"
OLD_NFT_MANAGER = "0x9BD490113a249c81D0beA52d677134f5e87C0d60"
NFT_DESCRIPTOR_LIB = "0x98904715dDd961fb368eF7ea3A419ff1FB664c38"
TICK_LENS = "0xdB5F2Ca65aAeB277E36be69553E0e7aA3585204d"

# Pool initialization code hashes
V2_PAIR_INIT_CODE_HASH = "0x60cc0e9ad39c5fa4ee52571f511012ed76fbaa9bbaffd2f3fafffcb3c47cff6e"
V3_POOL_INIT_CODE_HASH = "0x209015062f691a965df159762a8d966b688e328361c53ec32da2ad31287e3b72"

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
        
        # Add PoA middleware to handle extraData field in Flare Network
        if ExtraDataToPOAMiddleware not in self.web3.middleware_onion:
            self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            
        self.logger = logger.bind(service="defi")

        # Initialize contract instances
        self.v2_router = self.web3.eth.contract(
            address=self.web3.to_checksum_address(UNISWAP_V2_ROUTER),
            abi=UNISWAP_V2_ROUTER_ABI,
        )

        self.v3_router = self.web3.eth.contract(
            address=self.web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=UNISWAP_V3_ROUTER_ABI,
        )

        self.v3_position_manager = self.web3.eth.contract(
            address=self.web3.to_checksum_address(UNISWAP_V3_POSITION_MANAGER),
            abi=UNISWAP_V3_NFT_MANAGER_ABI,
        )

        # Map token symbols to addresses
        self.token_addresses = TOKEN_ADDRESSES

    def _get_token_contract(self, token_address: str) -> Contract:
        """Get a contract instance for an ERC20 token."""
        return self.web3.eth.contract(
            address=self.web3.to_checksum_address(token_address), abi=ERC20_ABI
        )

    def _get_wflr_contract(self) -> Contract:
        """Get a contract instance for the WFLR token with the proper ABI including deposit()."""
        wflr_address = self.token_addresses.get("WFLR")
        if not wflr_address:
            raise ValueError("WFLR token address not found")
        return self.web3.eth.contract(
            address=self.web3.to_checksum_address(wflr_address), abi=WFLR_ABI
        )

    def _get_eip1559_tx_params(self) -> dict[str, Any]:
        """
        Get standard EIP-1559 transaction parameters.
        
        Returns:
            Dictionary of base transaction parameters
        """
        return {
            "maxFeePerGas": self.web3.eth.gas_price,
            "maxPriorityFeePerGas": self.web3.eth.max_priority_fee,
            "chainId": self.web3.eth.chain_id,
            "type": 2,  # EIP-1559 transaction
        }

    def _approve_token_if_needed(
        self, token_address: str, spender: str, amount: int, sender: str
    ) -> dict[str, Any] | None:
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
            "from": sender,
            "to": token_address,
            "gas": 100000,  # Estimate gas in production
            "nonce": self.web3.eth.get_transaction_count(sender),
            "data": token_contract.functions.approve(spender, amount).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})["data"],
            **self._get_eip1559_tx_params()
        }

        self.logger.info(
            "token_approval", token=token_address, spender=spender, amount=amount
        )
        return tx

    def create_v2_swap_tx(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        sender: str,
        slippage: Decimal = DEFAULT_SLIPPAGE,
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
            sender=sender,
        )

        # Get token addresses
        from_token_address = self.token_addresses.get(from_token.upper())
        to_token_address = self.token_addresses.get(to_token.upper())

        if not from_token_address or not to_token_address:
            raise ValueError(
                f"Unknown token: {from_token if not from_token_address else to_token}"
            )

        # Handle native token (FLR)
        is_exact_eth_for_tokens = from_token.upper() == "FLR"
        is_exact_tokens_for_eth = to_token.upper() == "FLR"

        # Convert amount to wei
        amount_in_wei = self.web3.to_wei(amount, "ether")

        # Calculate min amount out with slippage
        # In production, would query price first for better estimation
        amount_out_min = int(amount_in_wei * (1 - slippage))

        # Set deadline
        deadline = self.web3.eth.get_block("latest").timestamp + DEFAULT_DEADLINE

        # Determine the swap path
        if is_exact_eth_for_tokens:
            path = [self.token_addresses["WFLR"], to_token_address]
            fn_name = "swapExactETHForTokens"
            value = amount_in_wei
            args = [amount_out_min, path, sender, deadline]
        elif is_exact_tokens_for_eth:
            path = [from_token_address, self.token_addresses["WFLR"]]
            fn_name = "swapExactTokensForETH"
            value = 0
            args = [amount_in_wei, amount_out_min, path, sender, deadline]
        else:
            path = [from_token_address, to_token_address]
            fn_name = "swapExactTokensForTokens"
            value = 0
            args = [amount_in_wei, amount_out_min, path, sender, deadline]

        # Create swap transaction
        swap_tx = {
            "from": sender,
            "to": self.v2_router.address,
            "gas": 300000,  # Estimate gas in production
            "nonce": self.web3.eth.get_transaction_count(sender),
            "value": value,
            "data": self.v2_router.functions[fn_name](*args).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})["data"],
            **self._get_eip1559_tx_params()
        }

        # Create approval transaction if needed
        approval_tx = None
        if not is_exact_eth_for_tokens:
            approval_tx = self._approve_token_if_needed(
                from_token_address, self.v2_router.address, amount_in_wei, sender
            )

        return swap_tx, approval_tx

    def create_v3_swap_tx(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        sender: str,
        fee_tier: int = 3000,  # 0.3% fee tier
        slippage: Decimal = DEFAULT_SLIPPAGE,
        include_wflr_steps: bool = True,  # Whether to include wrap and approve steps for FLR
    ) -> list[dict[str, Any]]:
        """
        Create transaction(s) for swapping tokens using Uniswap V3.
        
        For FLR to token swaps, this method now includes:
        1. Transaction to wrap FLR to WFLR
        2. Transaction to approve WFLR for router
        3. Transaction to swap WFLR to destination token
        
        All necessary transactions are returned in the correct sequence.

        Args:
            from_token: Symbol of the token to swap from
            to_token: Symbol of the token to swap to
            amount: Amount to swap in original units (not wei)
            sender: Address of the sender
            fee_tier: Fee tier (500, 3000, 10000)
            slippage: Maximum acceptable slippage
            include_wflr_steps: Whether to include wrap and approve steps for FLR

        Returns:
            List of transaction dictionaries in execution order.
            For non-FLR source tokens: [approval_tx (if needed), swap_tx]
            For FLR source tokens: [wrap_tx, approve_tx, swap_tx]
        """
        self.logger.info(
            "creating_v3_swap",
            from_token=from_token,
            to_token=to_token,
            amount=amount,
            sender=sender,
            fee_tier=fee_tier,
        )

        # Prepare return list
        transactions = []
        
        # Get token addresses
        is_flr_source = from_token.upper() == "FLR"
        wflr_address = self.token_addresses.get("WFLR")
        to_token_address = self.token_addresses.get(to_token.upper())

        if not to_token_address:
            raise ValueError(f"Unknown token: {to_token}")
        
        if is_flr_source and not wflr_address:
            raise ValueError("WFLR token address not found")

        # Convert amount to wei
        amount_in_wei = self.web3.to_wei(amount, "ether")

        # Calculate min amount out with slippage
        # In production, would query price first for better estimation
        amount_out_min = int(amount_in_wei * (1 - slippage))

        # Set deadline
        deadline = self.web3.eth.get_block("latest").timestamp + DEFAULT_DEADLINE
        
        # Get initial nonce
        nonce = self.web3.eth.get_transaction_count(sender)
        
        # For FLR source, add wrapping and approval steps
        if is_flr_source and include_wflr_steps:
            # 1. Add transaction to wrap FLR to WFLR
            wflr_contract = self._get_wflr_contract()
            
            # Log details about the WFLR contract
            self.logger.info(
                "wrapping_flr_to_wflr",
                wflr_address=wflr_address,
                amount=amount,
                functions_available=str(wflr_contract.functions)
            )
            
            # Create deposit transaction data
            deposit_data = wflr_contract.functions.deposit().build_transaction({
                "gas": 0, 
                "gasPrice": 0, 
                "nonce": 0
            })["data"]
            
            wrap_tx = {
                "from": sender,
                "to": wflr_address,
                "value": amount_in_wei,
                "data": deposit_data,
                "gas": 200000,  # Gas limit for deposit
                "nonce": nonce,
                "gasPrice": self.web3.eth.gas_price,  # Use legacy gas pricing for Flare
                "chainId": self.web3.eth.chain_id
            }
            transactions.append(wrap_tx)
            nonce += 1
            
            # 2. Add transaction to approve WFLR for router
            approve_data = wflr_contract.functions.approve(
                self.v3_router.address, 
                amount_in_wei
            ).build_transaction({
                "gas": 0, 
                "gasPrice": 0, 
                "nonce": 0
            })["data"]
            
            approve_tx = {
                "from": sender,
                "to": wflr_address,
                "value": 0,
                "data": approve_data,
                "gas": 200000,  # Gas limit for approve
                "nonce": nonce,
                "gasPrice": self.web3.eth.gas_price,
                "chainId": self.web3.eth.chain_id
            }
            transactions.append(approve_tx)
            nonce += 1
            
            # Use WFLR as the source token for the swap
            from_token_address = wflr_address
        else:
            # For non-FLR token sources
            from_token_address = self.token_addresses.get(from_token.upper())
            if not from_token_address:
                raise ValueError(f"Unknown token: {from_token}")
                
            # Add approval transaction if needed and not a FLR source
            if not is_flr_source:
                approval_tx = self._approve_token_if_needed(
                    from_token_address, self.v3_router.address, amount_in_wei, sender
                )
                if approval_tx:
                    # Update the nonce and add to transactions
                    approval_tx["nonce"] = nonce
                    transactions.append(approval_tx)
                    nonce += 1

        # 3. Create swap transaction (for all cases)
        # Create params for exactInputSingle
        params = {
            "tokenIn": from_token_address,
            "tokenOut": to_token_address,
            "fee": fee_tier,
            "recipient": sender,
            "deadline": deadline,
            "amountIn": amount_in_wei,
            "amountOutMinimum": 0,
            "sqrtPriceLimitX96": 0,  # No price limit
        }

        # Create swap transaction
        swap_data = self.v3_router.functions.exactInputSingle(params).build_transaction({
            "gas": 0, 
            "gasPrice": 0, 
            "nonce": 0
        })["data"]
        
        swap_tx = {
            "from": sender,
            "to": self.v3_router.address,
            "gas": 1000000,  # Higher gas limit for swap
            "nonce": nonce,
            "value": 0,  # Value is 0 since we're using tokens (WFLR for FLR)
            "data": swap_data,
            "gasPrice": self.web3.eth.gas_price,  # Use legacy gas price for Flare
            "chainId": self.web3.eth.chain_id
        }
        transactions.append(swap_tx)

        self.logger.info(
            "v3_swap_transactions_created", 
            transaction_count=len(transactions),
            is_flr_source=is_flr_source
        )
        
        return transactions

    def create_swap_tx(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        sender: str,
        use_v3: bool = True,  # Default to V3 for better pricing
        fee_tier: int = 3000,  # 0.3% fee tier
        slippage: Decimal = DEFAULT_SLIPPAGE,
        include_flr_wrap: bool = True,  # Whether to include wrap and approve steps for FLR
    ) -> list[dict[str, Any]]:
        """
        Create a transaction for swapping tokens, using either V2 or V3 router.
        
        Args:
            from_token: Source token symbol
            to_token: Destination token symbol
            amount: Amount to swap (in token decimals)
            sender: Address of the sender
            use_v3: Whether to use V3 router (default True)
            fee_tier: Fee tier for V3 pool (ignored for V2)
            slippage: Maximum slippage tolerance
            include_flr_wrap: For FLR sources, whether to include wrap and approve steps
            
        Returns:
            List of transaction dictionaries in execution order:
            - For V2, non-FLR: [approval_tx (if needed), swap_tx]
            - For V3, non-FLR: [approval_tx (if needed), swap_tx]
            - For V3, FLR: [wrap_tx, approve_tx, swap_tx] (if include_flr_wrap=True)
        """
        # Validate inputs
        if not from_token or not to_token:
            raise ValueError("Both source and target tokens must be specified")
            
        if from_token.upper() == to_token.upper():
            raise ValueError("Source and target tokens must be different")
            
        if amount <= 0:
            raise ValueError("Amount must be positive")
            
        # Ensure sender is a valid address
        sender = self.web3.to_checksum_address(sender)
        
        # Create swap using requested version
        if use_v3:
            return self.create_v3_swap_tx(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                sender=sender,
                fee_tier=fee_tier,
                slippage=slippage,
                include_wflr_steps=include_flr_wrap,
            )
        else:
            # For V2 router, convert tuple to list
            swap_tx, approval_tx = self.create_v2_swap_tx(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                sender=sender,
                slippage=slippage,
            )
            
            transactions = []
            if approval_tx:
                transactions.append(approval_tx)
            transactions.append(swap_tx)
            
            return transactions

    def create_v2_add_liquidity_tx(
        self,
        token_a: str,
        token_b: str,
        amount_a: float,
        amount_b: float,
        sender: str,
        slippage: Decimal = DEFAULT_SLIPPAGE,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        Create transaction for adding liquidity to a Uniswap V2 pool.

        Args:
            token_a: Symbol of the first token
            token_b: Symbol of the second token
            amount_a: Amount of first token to add
            amount_b: Amount of second token to add
            sender: Address of the sender
            slippage: Maximum acceptable slippage

        Returns:
            Tuple of (add liquidity transaction, list of approval transactions if needed)
        """
        self.logger.info(
            "creating_v2_add_liquidity",
            token_a=token_a,
            token_b=token_b,
            amount_a=amount_a,
            amount_b=amount_b,
            sender=sender,
        )

        # Get token addresses - sort them alphabetically to match Uniswap's convention
        token_a_address = self.token_addresses.get(token_a.upper())
        token_b_address = self.token_addresses.get(token_b.upper())

        if not token_a_address or not token_b_address:
            raise ValueError(
                f"Unknown token: {token_a if not token_a_address else token_b}"
            )

        # Check if one of the tokens is the native token
        is_native_involved = token_a.upper() == "FLR" or token_b.upper() == "FLR"

        # Convert amounts to wei
        amount_a_wei = self.web3.to_wei(amount_a, "ether")
        amount_b_wei = self.web3.to_wei(amount_b, "ether")

        # Calculate min amounts based on slippage
        amount_a_min = int(amount_a_wei * (1 - slippage))
        amount_b_min = int(amount_b_wei * (1 - slippage))

        # Set deadline
        deadline = self.web3.eth.get_block("latest").timestamp + DEFAULT_DEADLINE

        approval_txs = []

        # Create the appropriate add liquidity transaction
        if is_native_involved:
            # For addLiquidityETH
            if token_a.upper() == "FLR":
                token = token_b_address
                token_amount = amount_b_wei
                token_amount_min = amount_b_min
                eth_amount = amount_a_wei
                eth_amount_min = amount_a_min

                # Build addLiquidityETH transaction
                tx = {
                    "from": sender,
                    "to": self.v2_router.address,
                    "gas": 300000,  # Estimate gas in production
                    "nonce": self.web3.eth.get_transaction_count(sender),
                    "value": eth_amount,
                    "data": self.v2_router.functions.addLiquidityETH(
                        token,
                        token_amount,
                        token_amount_min,
                        eth_amount_min,
                        sender,
                        deadline,
                    ).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})["data"],
                    **self._get_eip1559_tx_params()
                }

                # Add approval for the token if needed
                approval_tx = self._approve_token_if_needed(
                    token, self.v2_router.address, token_amount, sender
                )
                if approval_tx:
                    approval_txs.append(approval_tx)
            else:  # token_b.upper() == "FLR"
                token = token_a_address
                token_amount = amount_a_wei
                token_amount_min = amount_a_min
                eth_amount = amount_b_wei
                eth_amount_min = amount_b_min

                # Build addLiquidityETH transaction
                tx = {
                    "from": sender,
                    "to": self.v2_router.address,
                    "gas": 300000,  # Estimate gas in production
                    "nonce": self.web3.eth.get_transaction_count(sender),
                    "value": eth_amount,
                    "data": self.v2_router.functions.addLiquidityETH(
                        token,
                        token_amount,
                        token_amount_min,
                        eth_amount_min,
                        sender,
                        deadline,
                    ).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})["data"],
                    **self._get_eip1559_tx_params()
                }

                # Add approval for the token if needed
                approval_tx = self._approve_token_if_needed(
                    token, self.v2_router.address, token_amount, sender
                )
                if approval_tx:
                    approval_txs.append(approval_tx)
        else:
            # For regular addLiquidity
            # Build addLiquidity transaction
            tx = {
                "from": sender,
                "to": self.v2_router.address,
                "gas": 300000,  # Estimate gas in production
                "nonce": self.web3.eth.get_transaction_count(sender),
                "value": 0,
                "data": self.v2_router.functions.addLiquidity(
                    token_a_address,
                    token_b_address,
                    amount_a_wei,
                    amount_b_wei,
                    amount_a_min,
                    amount_b_min,
                    sender,
                    deadline,
                ).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})["data"],
                **self._get_eip1559_tx_params()
            }

            # Add approvals for both tokens if needed
            approval_tx_a = self._approve_token_if_needed(
                token_a_address, self.v2_router.address, amount_a_wei, sender
            )
            if approval_tx_a:
                approval_txs.append(approval_tx_a)

            approval_tx_b = self._approve_token_if_needed(
                token_b_address, self.v2_router.address, amount_b_wei, sender
            )
            if approval_tx_b:
                approval_txs.append(approval_tx_b)

        return tx, approval_txs

    def create_v3_add_liquidity_tx(
        self,
        token_a: str,
        token_b: str,
        amount_a: float,
        amount_b: float,
        sender: str,
        fee_tier: int = 3000,  # 0.3% fee tier
        slippage: Decimal = DEFAULT_SLIPPAGE,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        Create transaction for adding liquidity to a Uniswap V3 pool.

        Args:
            token_a: Symbol of the first token
            token_b: Symbol of the second token
            amount_a: Amount of first token to add
            amount_b: Amount of second token to add
            sender: Address of the sender
            fee_tier: Fee tier for the pool (500, 3000, 10000)
            slippage: Maximum acceptable slippage

        Returns:
            Tuple of (add liquidity transaction, list of approval transactions if needed)
        """
        self.logger.info(
            "creating_v3_add_liquidity",
            token_a=token_a,
            token_b=token_b,
            amount_a=amount_a,
            amount_b=amount_b,
            sender=sender,
            fee_tier=fee_tier,
        )

        # Get token addresses and sort them - Uniswap V3 requires tokens to be sorted
        token_a_address = self.token_addresses.get(token_a.upper())
        token_b_address = self.token_addresses.get(token_b.upper())

        if not token_a_address or not token_b_address:
            raise ValueError(
                f"Unknown token: {token_a if not token_a_address else token_b}"
            )

        # Sort tokens by address
        if token_a_address.lower() > token_b_address.lower():
            token_a_address, token_b_address = token_b_address, token_a_address
            amount_a, amount_b = amount_b, amount_a
            token_a, token_b = token_b, token_a

        # Convert amounts to wei
        amount_a_wei = self.web3.to_wei(amount_a, "ether")
        amount_b_wei = self.web3.to_wei(amount_b, "ether")

        # Calculate min amounts based on slippage
        amount_a_min = int(amount_a_wei * (1 - slippage))
        amount_b_min = int(amount_b_wei * (1 - slippage))

        # Set deadline
        deadline = self.web3.eth.get_block("latest").timestamp + DEFAULT_DEADLINE

        # For V3, we need to specify price range via ticks
        # In a real implementation, these would be calculated based on current price and desired range
        # For simplicity, we're using a full range position
        # These are not real values and would need to be properly calculated
        tick_spacing = 60  # For fee tier 3000
        if fee_tier == 500:
            tick_spacing = 10
        elif fee_tier == 10000:
            tick_spacing = 200

        # Simplification: full range position
        tick_lower = -887272  # MIN_TICK - (MIN_TICK % tick_spacing)
        tick_upper = 887272  # MAX_TICK - (MAX_TICK % tick_spacing)

        # Create params for mint
        params = {
            "token0": token_a_address,
            "token1": token_b_address,
            "fee": fee_tier,
            "tickLower": tick_lower,
            "tickUpper": tick_upper,
            "amount0Desired": amount_a_wei,
            "amount1Desired": amount_b_wei,
            "amount0Min": amount_a_min,
            "amount1Min": amount_b_min,
            "recipient": sender,
            "deadline": deadline,
        }

        # For native token (FLR) we need different handling
        is_native_involved = token_a.upper() == "FLR" or token_b.upper() == "FLR"
        value = 0

        if is_native_involved:
            if token_a.upper() == "FLR":
                value = amount_a_wei
            else:
                value = amount_b_wei

            # In a real implementation, we would use specialized methods for ETH
            # For simplicity, we're using the regular mint function

        # Build mint transaction
        tx = {
            "from": sender,
            "to": self.v3_position_manager.address,
            "gas": 500000,  # Estimate gas in production
            "nonce": self.web3.eth.get_transaction_count(sender),
            "value": value,
            "data": self.v3_position_manager.functions.mint(params).build_transaction({"gas": 0, "gasPrice": 0, "nonce": 0})["data"],
            **self._get_eip1559_tx_params()
        }

        # Add approval transactions for tokens if needed
        approval_txs = []

        if token_a.upper() != "FLR":
            approval_tx_a = self._approve_token_if_needed(
                token_a_address, self.v3_position_manager.address, amount_a_wei, sender
            )
            if approval_tx_a:
                approval_txs.append(approval_tx_a)

        if token_b.upper() != "FLR":
            approval_tx_b = self._approve_token_if_needed(
                token_b_address, self.v3_position_manager.address, amount_b_wei, sender
            )
            if approval_tx_b:
                approval_txs.append(approval_tx_b)

        return tx, approval_txs

    def create_add_liquidity_tx(
        self,
        token_a: str,
        token_b: str,
        amount_a: float,
        amount_b: float,
        sender: str,
        use_v3: bool = True,
        fee_tier: int = 3000,  # Only for V3
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        Create a transaction for adding liquidity, choosing between V2 and V3.

        Args:
            token_a: Symbol of the first token
            token_b: Symbol of the second token
            amount_a: Amount of first token to add
            amount_b: Amount of second token to add
            sender: Address of the sender
            use_v3: Whether to use V3 or V2
            fee_tier: Fee tier for V3 pools

        Returns:
            Tuple of (add_liquidity_tx, list of approval_txs)
            approval_txs may be empty if no approvals are needed
        """
        # Validate inputs
        if not token_a or not token_b:
            raise ValueError("Both tokens must be specified")
            
        if token_a.upper() == token_b.upper():
            raise ValueError("Tokens must be different")
            
        if amount_a <= 0 or amount_b <= 0:
            raise ValueError("Amounts must be positive")
            
        # Ensure sender is a valid address
        sender = self.web3.to_checksum_address(sender)
        
        # Create liquidity transaction using requested version
        if use_v3:
            return self.create_v3_add_liquidity_tx(
                token_a=token_a,
                token_b=token_b,
                amount_a=amount_a,
                amount_b=amount_b,
                sender=sender,
                fee_tier=fee_tier,
            )
        else:
            return self.create_v2_add_liquidity_tx(
                token_a=token_a,
                token_b=token_b,
                amount_a=amount_a,
                amount_b=amount_b,
                sender=sender,
            )

    def create_swap_flr_to_usdc_txs(
        self,
        amount: float,
        sender: str
    ) -> list[dict[str, Any]]:
        """
        Create transactions for the complete flow of swapping FLR to USDC.
        This is now a wrapper around create_v3_swap_tx with FLR and USDC as parameters.
        
        Args:
            amount: Amount of FLR to swap
            sender: Sender address
            
        Returns:
            List of transaction dictionaries [wrap_tx, approve_tx, swap_tx]
        """
        self.logger.info("creating_flr_to_usdc_transactions", amount=amount, sender=sender)
        
        # Just use the updated create_v3_swap_tx function
        transactions = self.create_v3_swap_tx(
            from_token="FLR",
            to_token="USDC",
            amount=amount,
            sender=sender,
            include_wflr_steps=True
        )
        
        # Verify we have the expected 3 transactions
        if len(transactions) != 3:
            raise ValueError(f"Expected 3 transactions, got {len(transactions)}")
            
        return transactions

    def swap_flr_to_usdc(
        self,
        amount: float,
        sender: str,
        private_key: str,
        slippage: Decimal = DEFAULT_SLIPPAGE,
        wait_for_receipts: bool = True
    ) -> list[str]:
        """
        Execute a complete flow to swap FLR to USDC, handling all steps:
        1. Wrap FLR to WFLR
        2. Approve WFLR for router
        3. Swap WFLR to USDC
        
        Args:
            amount: Amount of FLR to swap
            sender: Sender address
            private_key: Private key for signing transactions
            slippage: Maximum slippage tolerance
            wait_for_receipts: Whether to wait for transaction receipts
            
        Returns:
            List of transaction hashes in order [wrap_tx, approve_tx, swap_tx]
        """
        self.logger.info("starting_flr_to_usdc_swap", amount=amount, sender=sender)
        
        # Get transactions using create_v3_swap_tx with specific slippage
        transactions = self.create_v3_swap_tx(
            from_token="FLR",
            to_token="USDC",
            amount=amount,
            sender=sender,
            slippage=slippage,
            include_wflr_steps=True
        )
        
        # Verify we have the expected 3 transactions
        if len(transactions) != 3:
            raise ValueError(f"Expected 3 transactions, got {len(transactions)}")
        
        # Sign and send all transactions
        tx_hashes = []
        for i, tx in enumerate(transactions):
            step_name = ["wrap", "approve", "swap"][i]
            self.logger.info(f"sending_{step_name}_transaction", sender=sender)
            
            # Sign the transaction
            signed_tx = self.web3.eth.account.sign_transaction(tx, private_key)
            
            # Send the transaction
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hash_hex = tx_hash.hex()
            tx_hashes.append(tx_hash_hex)
            
            self.logger.info(
                f"{step_name}_transaction_sent",
                tx_hash=tx_hash_hex,
                sender=sender
            )
            
            # Wait for receipt if requested
            if wait_for_receipts:
                receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
                self.logger.info(
                    f"{step_name}_transaction_mined",
                    status=receipt["status"],
                    gas_used=receipt["gasUsed"],
                    block_number=receipt["blockNumber"]
                )
                
                # If the transaction failed, stop the process
                if receipt["status"] != 1:
                    raise ValueError(f"{step_name.capitalize()} transaction failed: {tx_hash_hex}")
        
        self.logger.info(
            "flr_to_usdc_swap_completed",
            wrap_tx=tx_hashes[0],
            approve_tx=tx_hashes[1],
            swap_tx=tx_hashes[2]
        )
        
        return tx_hashes
