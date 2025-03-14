"""
Flare Network Provider Module

This module provides a FlareProvider class for interacting with the Flare Network.
It handles account management, transaction queuing, and blockchain interactions.
"""

from dataclasses import dataclass
from typing import Any, Optional

import structlog
from eth_account import Account
from eth_typing import ChecksumAddress
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxParams

from flare_defai.blockchain.ftso import FTSOPriceFeed


@dataclass
class TxQueueElement:
    """
    Represents a transaction in the queue with its associated message.

    Attributes:
        msg (str): Description or context of the transaction
        tx (TxParams): Transaction parameters
    """

    msg: str
    tx: TxParams


logger = structlog.get_logger(__name__)


class FlareProvider:
    """
    Manages interactions with the Flare Network including account
    operations and transactions.

    Attributes:
        address (ChecksumAddress | None): The account's checksum address
        private_key (str | None): The account's private key
        tx_queue (list[TxQueueElement]): Queue of pending transactions
        w3 (Web3): Web3 instance for blockchain interactions
        logger (BoundLogger): Structured logger for the provider
        ftso_feed (FTSOPriceFeed): FTSO price feed for USD value calculations
    """

    def __init__(self, web3_provider_url: str) -> None:
        """
        Initialize the Flare Provider.

        Args:
            web3_provider_url (str): URL of the Web3 provider endpoint
        """
        self.address: ChecksumAddress | None = None
        self.private_key: str | None = None
        self.tx_queue: list[TxQueueElement] = []
        self.w3 = Web3(Web3.HTTPProvider("https://flare-api.flare.network/ext/C/rpc"))
        
        # Add PoA middleware to handle extraData field in Flare Network
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        self.logger = logger.bind(router="flare_provider")
        self.ftso_feed = FTSOPriceFeed()

    def reset(self) -> None:
        """
        Reset the provider state by clearing account details and transaction queue.
        """
        self.address = None
        self.private_key = None
        self.tx_queue = []
        self.logger.debug("reset", address=self.address, tx_queue=self.tx_queue)

    def add_tx_to_queue(self, msg: str, tx: TxParams) -> None:
        """
        Add a transaction to the queue with an associated message.

        Args:
            msg (str): Description of the transaction
            tx (TxParams): Transaction parameters
        """
        tx_queue_element = TxQueueElement(msg=msg, tx=tx)
        self.tx_queue.append(tx_queue_element)
        self.logger.debug("add_tx_to_queue", tx_queue=self.tx_queue)

    def send_tx_in_queue(self) -> str:
        """
        Send the first transaction in the queue.

        Returns:
            str: Transaction hash of the sent transaction

        Raises:
            ValueError: If no transaction is found in the queue
        """
        if not self.tx_queue:
            msg = "No transactions in queue"
            raise ValueError(msg)
            
        # Get the first transaction in the queue (FIFO)
        tx = self.tx_queue[0].tx
        
        try:
            tx_hash = self.sign_and_send_transaction(tx)
            self.logger.debug("sent_tx_hash", tx_hash=tx_hash)
            # Remove the transaction from the queue only if it was sent successfully
            self.tx_queue.pop(0)
            return tx_hash
        except Exception as e:
            self.logger.error("failed_to_send_transaction", error=str(e), tx=tx)
            # In case of failure, remove the transaction to avoid repeated attempts
            self.tx_queue.pop(0)
            raise

    def generate_account(self) -> ChecksumAddress:
        """
        Generate a new Flare account.

        Returns:
            ChecksumAddress: The checksum address of the generated account
        """
        account = Account.create()
        self.private_key = account.key.hex()
        self.address = self.w3.to_checksum_address(account.address)
        self.logger.debug(
            "generate_account", address=self.address, private_key=self.private_key
        )
        return self.address

    def sign_and_send_transaction(self, tx: TxParams) -> str:
        """
        Sign and send a transaction to the network.

        Args:
            tx (TxParams): Transaction parameters to be sent

        Returns:
            str: Transaction hash of the sent transaction

        Raises:
            ValueError: If account is not initialized
        """
        if not self.private_key or not self.address:
            msg = "Account not initialized"
            raise ValueError(msg)
        signed_tx = self.w3.eth.account.sign_transaction(
            tx, private_key=self.private_key
        )
        tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        self.w3.eth.wait_for_transaction_receipt(tx_hash)
        self.logger.debug("sign_and_send_transaction", tx=tx)
        return "0x" + tx_hash.hex()

    def check_balance(self) -> float:
        """
        Check the balance of the current account.

        Returns:
            float: Account balance in FLR

        Raises:
            ValueError: If account does not exist
        """
        if not self.address:
            msg = "Account does not exist"
            raise ValueError(msg)
        balance_wei = self.w3.eth.get_balance(self.address)
        self.logger.debug("check_balance", balance_wei=balance_wei)
        return float(self.w3.from_wei(balance_wei, "ether"))

    def check_balance_usd(self) -> tuple[float, float | None]:
        """
        Check the balance in native currency and convert to USD.

        Returns:
            tuple containing (balance_in_flr, balance_in_usd)
            Where balance_in_usd may be None if price feed is unavailable
        """
        if not self.address:
            return 0.0, None

        # Get balance in FLR
        balance_wei = self.w3.eth.get_balance(self.address)
        balance_flr = float(self.w3.from_wei(balance_wei, "ether"))

        # Convert to USD using FTSO price feed
        flr_price, _ = self.ftso_feed.get_price("FLR")
        if flr_price is not None:
            balance_usd = balance_flr * flr_price
        else:
            balance_usd = None

        return balance_flr, balance_usd

    def get_token_balances_with_usd(self) -> dict[str, tuple[float, float | None]]:
        """
        Get balances of all supported tokens with their USD values.
        
        Returns:
            Dictionary of token symbols to (balance, usd_value) tuples
            Where usd_value may be None if price data is unavailable
        """
        if not self.address:
            msg = "Account does not exist"
            raise ValueError(msg)
            
        flr_balance = self.check_balance()
        results = {"FLR": (flr_balance, self.ftso_feed.calculate_usd_value("FLR", flr_balance))}
        
        self.logger.debug("get_token_balances_with_usd", balances=results)
        
        # Add other tokens here as needed
        
        return results

    def create_send_flr_tx(self, to_address: str, amount: float) -> TxParams:
        """
        Create a transaction to send FLR tokens.

        Args:
            to_address (str): Recipient address
            amount (float): Amount of FLR to send

        Returns:
            TxParams: Transaction parameters for sending FLR

        Raises:
            ValueError: If account does not exist
        """
        if not self.address:
            msg = "Account does not exist"
            raise ValueError(msg)
        tx: TxParams = {
            "from": self.address,
            "nonce": self.w3.eth.get_transaction_count(self.address),
            "to": self.w3.to_checksum_address(to_address),
            "value": self.w3.to_wei(amount, unit="ether"),
            "gas": 21000,
            "maxFeePerGas": self.w3.eth.gas_price,
            "maxPriorityFeePerGas": self.w3.eth.max_priority_fee,
            "chainId": self.w3.eth.chain_id,
            "type": 2,
        }
        return tx
