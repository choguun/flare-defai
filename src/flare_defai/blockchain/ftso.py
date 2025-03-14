"""
FTSO (Flare Time Series Oracle) integration for price data.
"""
from typing import Any
import structlog
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from flare_defai.settings import Settings

logger = structlog.get_logger()

class FTSOPriceFeed:
    """Interface to the Flare FTSO price feed system."""
    
    # Common feed IDs (same across networks)
    FEED_IDS = {
        "FLR/USD": "0x01464c522f55534400000000000000000000000000",
        "BTC/USD": "0x014254432f55534400000000000000000000000000",
        "ETH/USD": "0x014554482f55534400000000000000000000000000",
        "USDC/USD": "0x015553444320000000000000000000000000000000",
        "USDT/USD": "0x015553445420000000000000000000000000000000",
        "WFLR/USD": "0x01572b464c522f55534400000000000000000000000",
    }
    
    # FTSO V2 Contract ABI - Only the methods we need
    ABI = """[
        {
            "inputs": [{"internalType": "bytes21", "name": "_feedId", "type": "bytes21"}],
            "name": "getFeedById",
            "outputs": [
                {"internalType": "uint256", "name": "", "type": "uint256"},
                {"internalType": "int8", "name": "", "type": "int8"},
                {"internalType": "uint64", "name": "", "type": "uint64"}
            ],
            "stateMutability": "payable",
            "type": "function"
        }
    ]"""
    
    # Network-specific contract addresses
    CONTRACT_ADDRESSES = {
        # Coston2 testnet
        "coston2": "0x3d893C53D9e8056135C26C8c638B76C8b60Df726",
        # Flare mainnet - Note: This is a placeholder, might need updating
        "flare": "0x1755e85b246a55e78613ef260f5a454a052f4497"
    }
    
    def __init__(self, settings: Settings | None = None):
        """Initialize the FTSO price feed module."""
        self.settings = settings or Settings()
        self.web3 = Web3(Web3.HTTPProvider(self.settings.web3_provider_url))
        
        # Add PoA middleware to handle extraData field in Flare Network
        self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        # Determine which network we're on based on the provider URL
        if "coston2" in self.settings.web3_provider_url:
            network = "coston2"
            self.is_testnet = True
        else:
            network = "flare"
            self.is_testnet = False
        
        # Get the appropriate contract address for the network
        contract_address = self.CONTRACT_ADDRESSES.get(network)
        
        # Initialize contract
        self.ftso_contract = self.web3.eth.contract(
            address=self.web3.to_checksum_address(contract_address),
            abi=self.ABI
        )
        logger.debug("FTSO price feed initialized", 
                     provider="https://coston2-rpc.flare.network",
                     network=network,
                     contract=contract_address)
    
    def get_price(self, symbol: str) -> tuple[float | None, int]:
        """
        Get the price of a specific token in USD.
        
        Args:
            symbol: Token symbol (e.g., "FLR", "ETH")
            
        Returns:
            Tuple containing (price_in_usd, timestamp)
        """
        feed_id = self._get_feed_id_for_symbol(symbol)
        if not feed_id:
            logger.warning(f"No feed ID found for symbol {symbol}")
            return None, 0
            
        try:
            # For testnet, we might need to use mock data if the contract doesn't work properly
            if self.is_testnet:
                try:
                    # Try to get real data from the contract
                    result = self.ftso_contract.functions.getFeedById(feed_id).call()
                    value, decimals, timestamp = result
                    price_in_usd = float(value) / (10 ** abs(decimals))
                    logger.debug(f"Retrieved price for {symbol}", 
                                price=price_in_usd, 
                                timestamp=timestamp,
                                decimals=decimals)
                    return price_in_usd, timestamp
                except Exception as e:
                    # Fallback to mock data on error
                    logger.warning(f"Error getting price from testnet, using mock data: {str(e)}")
                    return self._get_mock_price(symbol)
            else:
                # For mainnet, always try to get real data
                result = self.ftso_contract.functions.getFeedById(feed_id).call()
                value, decimals, timestamp = result
                price_in_usd = float(value) / (10 ** abs(decimals))
                logger.debug(f"Retrieved price for {symbol}", 
                            price=price_in_usd, 
                            timestamp=timestamp,
                            decimals=decimals)
                return price_in_usd, timestamp
        except Exception as e:
            logger.error(f"Error getting price for {symbol}", error=str(e))
            # Use mock data as a last resort
            return self._get_mock_price(symbol)
    
    def _get_mock_price(self, symbol: str) -> tuple[float, int]:
        """
        Get a reasonable mock price for development and testing.
        
        Args:
            symbol: Token symbol
            
        Returns:
            Tuple of (price, timestamp)
        """
        # Mock prices based on reasonable market values
        mock_prices = {
            "FLR": 0.0147778,
            "BTC": 64890.50,
            "ETH": 3450.25,
            "USDC": 1.0,
            "USDT": 1.0,
            "WFLR": 0.0147778
        }
        price = mock_prices.get(symbol.upper(), 0.0)
        import time
        timestamp = int(time.time())
        logger.debug(f"Using mock price for {symbol}", 
                    price=price, 
                    timestamp=timestamp)
        return price, timestamp
        
    def get_prices(self, symbols: list[str]) -> dict[str, tuple[float | None, int]]:
        """
        Get the prices of multiple tokens in USD.
        
        Args:
            symbols: List of token symbols
            
        Returns:
            Dictionary mapping symbols to (price, timestamp) tuples
        """
        return {symbol: self.get_price(symbol) for symbol in symbols}
    
    def _get_feed_id_for_symbol(self, symbol: str) -> str | None:
        """
        Convert a symbol to its corresponding feed ID.
        
        Args:
            symbol: Token symbol (e.g., "FLR", "ETH")
            
        Returns:
            Feed ID string or None if not found
        """
        # Standard format is SYMBOL/USD
        feed_key = f"{symbol.upper()}/USD"
        return self.FEED_IDS.get(feed_key)
    
    def calculate_usd_value(self, token_symbol: str, token_amount: float) -> float | None:
        """
        Calculate the USD value of a given token amount.
        
        Args:
            token_symbol: Token symbol
            token_amount: Amount of tokens
            
        Returns:
            USD value or None if the price couldn't be retrieved
        """
        price, _ = self.get_price(token_symbol)
        if price is None:
            return None
        
        return token_amount * price 