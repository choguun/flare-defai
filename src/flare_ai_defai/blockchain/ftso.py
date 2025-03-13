"""
FTSO (Flare Time Series Oracle) integration for price data.
"""
from typing import Dict, List, Tuple, Union
import structlog
from web3 import Web3

from flare_ai_defai.settings import Settings

logger = structlog.get_logger()

class FTSOPriceFeed:
    """Interface to the Flare FTSO price feed system."""
    
    # FTSO V2 addresses
    # See https://dev.flare.network/ftso/solidity-reference
    FTSO_V2_ADDRESS = "0x3d893C53D9e8056135C26C8c638B76C8b60Df726"  # Coston2
    
    # Common feed IDs
    FEED_IDS = {
        "FLR/USD": "0x01464c522f55534400000000000000000000000000",
        "BTC/USD": "0x014254432f55534400000000000000000000000000",
        "ETH/USD": "0x014554482f55534400000000000000000000000000",
        "USDC/USD": "0x015553444320000000000000000000000000000000",
        "USDT/USD": "0x015553445420000000000000000000000000000000",
        "WFLR/USD": "0x01572b464c522f55534400000000000000000000000",
    }
    
    # ABI for FTSO V2
    ABI = """[{"inputs":[{"internalType":"address","name":"_addressUpdater","type":"address"}],"stateMutability":"nonpayable","type":"constructor"},{"inputs":[],"name":"FTSO_PROTOCOL_ID","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"fastUpdater","outputs":[{"internalType":"contract IFastUpdater","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"fastUpdatesConfiguration","outputs":[{"internalType":"contract IFastUpdatesConfiguration","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"getAddressUpdater","outputs":[{"internalType":"address","name":"_addressUpdater","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"bytes21","name":"_feedId","type":"bytes21"}],"name":"getFeedById","outputs":[{"internalType":"uint256","name":"","type":"uint256"},{"internalType":"int8","name":"","type":"int8"},{"internalType":"uint64","name":"","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"bytes21","name":"_feedId","type":"bytes21"}],"name":"getFeedByIdInWei","outputs":[{"internalType":"uint256","name":"_value","type":"uint256"},{"internalType":"uint64","name":"_timestamp","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"_index","type":"uint256"}],"name":"getFeedByIndex","outputs":[{"internalType":"uint256","name":"","type":"uint256"},{"internalType":"int8","name":"","type":"int8"},{"internalType":"uint64","name":"","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"_index","type":"uint256"}],"name":"getFeedByIndexInWei","outputs":[{"internalType":"uint256","name":"_value","type":"uint256"},{"internalType":"uint64","name":"_timestamp","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256","name":"_index","type":"uint256"}],"name":"getFeedId","outputs":[{"internalType":"bytes21","name":"","type":"bytes21"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"bytes21","name":"_feedId","type":"bytes21"}],"name":"getFeedIndex","outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"bytes21[]","name":"_feedIds","type":"bytes21[]"}],"name":"getFeedsById","outputs":[{"internalType":"uint256[]","name":"","type":"uint256[]"},{"internalType":"int8[]","name":"","type":"int8[]"},{"internalType":"uint64","name":"","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"bytes21[]","name":"_feedIds","type":"bytes21[]"}],"name":"getFeedsByIdInWei","outputs":[{"internalType":"uint256[]","name":"_values","type":"uint256[]"},{"internalType":"uint64","name":"_timestamp","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256[]","name":"_indices","type":"uint256[]"}],"name":"getFeedsByIndex","outputs":[{"internalType":"uint256[]","name":"","type":"uint256[]"},{"internalType":"int8[]","name":"","type":"int8[]"},{"internalType":"uint64","name":"","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[{"internalType":"uint256[]","name":"_indices","type":"uint256[]"}],"name":"getFeedsByIndexInWei","outputs":[{"internalType":"uint256[]","name":"_values","type":"uint256[]"},{"internalType":"uint64","name":"_timestamp","type":"uint64"}],"stateMutability":"payable","type":"function"},{"inputs":[],"name":"relay","outputs":[{"internalType":"contract IRelay","name":"","type":"address"}],"stateMutability":"view","type":"function"},{"inputs":[{"internalType":"bytes32[]","name":"_contractNameHashes","type":"bytes32[]"},{"internalType":"address[]","name":"_contractAddresses","type":"address[]"}],"name":"updateContractAddresses","outputs":[],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"components":[{"internalType":"bytes32[]","name":"proof","type":"bytes32[]"},{"components":[{"internalType":"uint32","name":"votingRoundId","type":"uint32"},{"internalType":"bytes21","name":"id","type":"bytes21"},{"internalType":"int32","name":"value","type":"int32"},{"internalType":"uint16","name":"turnoutBIPS","type":"uint16"},{"internalType":"int8","name":"decimals","type":"int8"}],"internalType":"struct FtsoV2Interface.FeedData","name":"body","type":"tuple"}],"internalType":"struct FtsoV2Interface.FeedDataWithProof","name":"_feedData","type":"tuple"}],"name":"verifyFeedData","outputs":[{"internalType":"bool","name":"","type":"bool"}],"stateMutability":"view","type":"function"}]"""
    
    def __init__(self, settings: Settings = None):
        """Initialize the FTSO price feed module."""
        self.settings = settings or Settings()
        self.web3 = Web3(Web3.HTTPProvider(self.settings.web3_provider_url))
        self.ftso_contract = self.web3.eth.contract(
            address=self.web3.to_checksum_address(self.FTSO_V2_ADDRESS),
            abi=self.ABI
        )
        logger.debug("FTSO price feed initialized", 
                     provider=self.settings.web3_provider_url,
                     contract=self.FTSO_V2_ADDRESS)
    
    def get_price(self, symbol: str) -> Tuple[float, int]:
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
            # Call the FTSO contract to get the price
            result = self.ftso_contract.functions.getFeedById(feed_id).call()
            value, decimals, timestamp = result
            
            # Convert the price to USD based on decimals
            price_in_usd = float(value) / (10 ** abs(decimals))
            logger.debug(f"Retrieved price for {symbol}", 
                        price=price_in_usd, 
                        timestamp=timestamp,
                        decimals=decimals)
            return price_in_usd, timestamp
        except Exception as e:
            logger.error(f"Error getting price for {symbol}", error=str(e))
            return None, 0
    
    def get_prices(self, symbols: List[str]) -> Dict[str, Tuple[float, int]]:
        """
        Get prices for multiple tokens in USD.
        
        Args:
            symbols: List of token symbols
            
        Returns:
            Dictionary mapping symbols to (price, timestamp) tuples
        """
        feed_ids = []
        valid_symbols = []
        
        for symbol in symbols:
            feed_id = self._get_feed_id_for_symbol(symbol)
            if feed_id:
                feed_ids.append(feed_id)
                valid_symbols.append(symbol)
        
        if not feed_ids:
            return {}
            
        try:
            # Call the FTSO contract to get multiple prices
            result = self.ftso_contract.functions.getFeedsById(feed_ids).call()
            values, decimals, timestamp = result
            
            # Create a dictionary of results
            prices = {}
            for i, symbol in enumerate(valid_symbols):
                price_in_usd = float(values[i]) / (10 ** abs(decimals[i]))
                prices[symbol] = (price_in_usd, timestamp)
                
            return prices
        except Exception as e:
            logger.error("Error getting multiple prices", error=str(e))
            return {}
    
    def calculate_usd_value(self, token_symbol: str, token_amount: float) -> float:
        """
        Calculate the USD value of a token amount.
        
        Args:
            token_symbol: Symbol of the token
            token_amount: Amount of the token
            
        Returns:
            USD value of the token amount
        """
        price, _ = self.get_price(token_symbol)
        if price is None:
            return None
        
        return token_amount * price
    
    def _get_feed_id_for_symbol(self, symbol: str) -> Union[str, None]:
        """
        Get the feed ID for a given token symbol.
        
        Args:
            symbol: Token symbol
            
        Returns:
            Feed ID for the token or None if not found
        """
        symbol = symbol.upper()
        feed_key = f"{symbol}/USD"
        
        # Handle the special case for FLR since there's both FLR/USD and WFLR/USD
        if symbol == "WFLR":
            return self.FEED_IDS.get("WFLR/USD")
        elif symbol == "FLR":
            return self.FEED_IDS.get("FLR/USD")
        
        # Try to find the symbol directly
        if feed_key in self.FEED_IDS:
            return self.FEED_IDS[feed_key]
        
        # If not found, log a warning
        logger.warning(f"No feed ID defined for {symbol}", symbol=symbol)
        return None 