"""
Chat Router Module

This module implements the main chat routing system for the AI Agent API.
It handles message routing, blockchain interactions, attestations, and AI responses.

The module provides a ChatRouter class that integrates various services:
- AI capabilities through GeminiProvider
- Blockchain operations through FlareProvider
- Attestation services through Vtpm
- Prompt management through PromptService
"""

import json

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from web3 import Web3
from web3.exceptions import Web3RPCError

from flare_defai.ai import GeminiProvider
from flare_defai.attestation import Vtpm, VtpmAttestationError
from flare_defai.blockchain import FlareProvider
from flare_defai.blockchain.defi import DeFiService
from flare_defai.prompts import PromptService, SemanticRouterResponse
from flare_defai.settings import settings
from flare_defai.blockchain.transaction_validator import SecureTransactionValidator, TransactionRisk
from flare_defai.api.dependencies import get_transaction_validator

logger = structlog.get_logger(__name__)
router = APIRouter()


class ChatMessage(BaseModel):
    """
    Pydantic model for chat message validation.

    Attributes:
        message (str): The chat message content, must not be empty
    """

    message: str = Field(..., min_length=1)


class ChatRouter:
    """
    Main router class handling chat messages and their routing to appropriate handlers.

    This class integrates various services and provides routing logic for different
    types of chat messages including blockchain operations, attestations, and general
    conversation.

    Attributes:
        ai (GeminiProvider): Provider for AI capabilities
        blockchain (FlareProvider): Provider for blockchain operations
        attestation (Vtpm): Provider for attestation services
        prompts (PromptService): Service for managing prompts
        logger (BoundLogger): Structured logger for the chat router
    """

    def __init__(
        self,
        ai: GeminiProvider,
        blockchain: FlareProvider,
        attestation: Vtpm,
        prompts: PromptService,
        transaction_validator: SecureTransactionValidator = None,
    ) -> None:
        """
        Initialize the ChatRouter with required service providers.

        Args:
            ai: Provider for AI capabilities
            blockchain: Provider for blockchain operations
            attestation: Provider for attestation services
            prompts: Service for managing prompts
            transaction_validator: Provider for transaction validation
        """
        self._router = APIRouter()
        self.ai = ai
        self.blockchain = blockchain
        self.attestation = attestation
        self.prompts = prompts
        self.logger = logger.bind(router="chat")
        self.defi = DeFiService(self.blockchain.w3)
        self.transaction_validator = transaction_validator
        self._setup_routes()

    def _setup_routes(self) -> None:
        """
        Set up FastAPI routes for the chat endpoint.
        Handles message routing, command processing, and transaction confirmations.
        """

        @self._router.post("/")
        async def chat(message: ChatMessage) -> dict[str, str]:  # pyright: ignore [reportUnusedFunction]
            """
            Process incoming chat messages and route them to appropriate handlers.

            Args:
                message: Validated chat message

            Returns:
                dict[str, str]: Response containing handled message result

            Raises:
                HTTPException: If message handling fails
            """
            try:
                self.logger.debug("received_message", message=message.message)

                if message.message.startswith("/"):
                    return await self.handle_command(message.message)
                if (
                    self.blockchain.tx_queue
                    and message.message.lower() in ["confirm", "confirmed"]
                ):
                    # Process all transactions in the queue one by one
                    tx_hashes = []
                    tx_count = len(self.blockchain.tx_queue)
                    
                    try:
                        # For multi-transaction flows like swaps, we need to process all 
                        # transactions in the queue in sequence
                        for i in range(tx_count):
                            if not self.blockchain.tx_queue:
                                break  # Queue might be empty if errors occurred
                                
                            # Get transaction description before sending
                            tx_description = self.blockchain.tx_queue[0].msg
                            self.logger.info(f"Processing transaction {i+1}/{tx_count}: {tx_description}")
                            
                            # Get the transaction from the queue without popping it yet
                            current_tx = self.blockchain.tx_queue[0].tx
                            
                            # Validate the transaction if a validator is available
                            if self.transaction_validator:
                                validation_result = await self.validate_transaction_before_sending(current_tx)
                                
                                # If the transaction is deemed invalid (high risk), don't send it
                                if not validation_result["is_valid"]:
                                    self.logger.warning(
                                        "transaction_blocked_by_validation",
                                        risk_level=validation_result["risk_level"],
                                        warnings=validation_result.get("warnings", [])
                                    )
                                    return {"response": validation_result["message"]}
                                
                                # For medium/low risk transactions, inform the user but proceed
                                if validation_result["risk_level"] not in ["safe", "unknown"]:
                                    self.logger.info(
                                        "transaction_validated_with_warnings",
                                        risk_level=validation_result["risk_level"]
                                    )
                            
                            # Send the transaction and get the hash
                            tx_hash = self.blockchain.send_tx_in_queue()
                            tx_hashes.append(tx_hash)
                            
                    except Web3RPCError as e:
                        self.logger.exception("send_tx_failed", error=str(e))
                        msg = (
                            f"Unfortunately the transaction failed with the error:\n{e.args[0]}"
                        )
                        return {"response": msg}
                    
                    # If we have transaction hashes, confirm the last one (or the only one)
                    if tx_hashes:
                        prompt, mime_type, schema = self.prompts.get_formatted_prompt(
                            "tx_confirmation",
                            tx_hash=tx_hashes[-1],  # Use the last transaction hash
                            block_explorer="https://flare-explorer.flare.network/",
                        )
                        tx_confirmation_response = self.ai.generate(
                            prompt=prompt,
                            response_mime_type=mime_type,
                            response_schema=schema,
                        )
                        
                        # For multi-transaction flows, include all tx hashes
                        if len(tx_hashes) > 1:
                            hashes_text = "\n".join([
                                f"Transaction {i+1}: {hash}" 
                                for i, hash in enumerate(tx_hashes)
                            ])
                            return {"response": f"{tx_confirmation_response.text}\n\nAll transactions completed successfully:\n{hashes_text}"}
                        else:
                            return {"response": tx_confirmation_response.text}
                    else:
                        return {"response": "No transactions were processed. Please try again."}
                if self.attestation.attestation_requested:
                    try:
                        resp = self.attestation.get_token([message.message])
                    except VtpmAttestationError as e:
                        resp = f"The attestation failed with  error:\n{e.args[0]}"
                    self.attestation.attestation_requested = False
                    return {"response": resp}

                route = await self.get_semantic_route(message.message)
                return await self.route_message(route, message.message)

            except Exception as e:
                self.logger.exception("message_handling_failed", error=str(e))
                raise HTTPException(status_code=500, detail=str(e)) from e

    @property
    def router(self) -> APIRouter:
        """Get the FastAPI router with registered routes."""
        return self._router

    async def handle_command(self, command: str) -> dict[str, str]:
        """
        Handle special command messages starting with '/'.

        Args:
            command: Command string to process

        Returns:
            dict[str, str]: Response containing command result
        """
        if command == "/reset":
            self.blockchain.reset()
            self.ai.reset()
            return {"response": "Reset complete"}
        return {"response": "Unknown command"}

    async def get_semantic_route(self, message: str) -> SemanticRouterResponse:
        """
        Determine the semantic route for a message using AI provider.

        Args:
            message: Message to route

        Returns:
            SemanticRouterResponse: Determined route for the message
        """
        try:
            prompt, mime_type, schema = self.prompts.get_formatted_prompt(
                "semantic_router", user_input=message
            )
            route_response = self.ai.generate(
                prompt=prompt, response_mime_type=mime_type, response_schema=schema
            )
            return SemanticRouterResponse(route_response.text)
        except Exception as e:
            self.logger.exception("routing_failed", error=str(e))
            return SemanticRouterResponse.CONVERSATIONAL

    async def route_message(
        self, route: SemanticRouterResponse, message: str
    ) -> dict[str, str]:
        """
        Route a message to the appropriate handler based on semantic route.

        Args:
            route: Determined semantic route
            message: Original message to handle

        Returns:
            dict[str, str]: Response from the appropriate handler
        """
        handlers = {
            SemanticRouterResponse.GENERATE_ACCOUNT: self.handle_generate_account,
            SemanticRouterResponse.SEND_TOKEN: self.handle_send_token,
            SemanticRouterResponse.SWAP_TOKEN: self.handle_swap_token,
            SemanticRouterResponse.ADD_LIQUIDITY: self.handle_add_liquidity,
            SemanticRouterResponse.CHECK_BALANCE: self.handle_check_balance,
            SemanticRouterResponse.REQUEST_ATTESTATION: self.handle_attestation,
            SemanticRouterResponse.CONVERSATIONAL: self.handle_conversation,
        }

        handler = handlers.get(route)
        if not handler:
            return {"response": "Unsupported route"}

        return await handler(message)

    async def handle_generate_account(self, _: str) -> dict[str, str]:
        """
        Handle account generation requests.

        Args:
            _: Unused message parameter

        Returns:
            dict[str, str]: Response containing new account information
                or existing account
        """
        if self.blockchain.address:
            # Get balance in both FLR and USD
            flr_balance, usd_balance = self.blockchain.check_balance_usd()
            usd_display = f"(${usd_balance:.2f})" if usd_balance is not None else "(USD value unavailable)"
            return {"response": f"Account exists - {self.blockchain.address}\nBalance: {flr_balance:.6f} FLR {usd_display}"}
            
        address = self.blockchain.generate_account()
        prompt, mime_type, schema = self.prompts.get_formatted_prompt(
            "generate_account", address=address
        )
        gen_address_response = self.ai.generate(
            prompt=prompt, response_mime_type=mime_type, response_schema=schema
        )
        return {"response": gen_address_response.text}

    async def handle_send_token(self, message: str) -> dict[str, str]:
        """
        Handle token sending requests.

        Args:
            message: User message containing token sending details

        Returns:
            dict[str, str]: Response containing transaction result
        """
        if not self.blockchain.address:
            return {"response": "No account exists. Please create an account first with 'Create an account for me'."}

        prompt, mime_type, schema = self.prompts.get_formatted_prompt(
            "token_send", user_input=message
        )
        send_token_response = self.ai.generate(
            prompt=prompt, response_mime_type=mime_type, response_schema=schema
        )
        
        try:
            send_token_json = json.loads(send_token_response.text)
            
            # Check for all required fields
            expected_json_len = 2
            has_to_address = "to_address" in send_token_json
            has_amount = "amount" in send_token_json and send_token_json.get("amount") != 0.0
            
            if not (has_to_address and has_amount):
                self.logger.debug(
                    "send_token_validation_failed", 
                    response_json=send_token_response.text,
                    has_to_address=has_to_address,
                    has_amount=has_amount
                )
                
                # Request more details with the follow-up prompt
                prompt, mime_type, schema = self.prompts.get_formatted_prompt("follow_up_token_send")
                follow_up_response = self.ai.generate(prompt=prompt, response_mime_type=mime_type, response_schema=schema)
                return {"response": follow_up_response.text}
                
        except (json.JSONDecodeError, KeyError) as e:
            self.logger.error("send_token_json_error", error=str(e), response=send_token_response.text)
            # Request more details with the follow-up prompt
            prompt, mime_type, schema = self.prompts.get_formatted_prompt("follow_up_token_send")
            follow_up_response = self.ai.generate(prompt=prompt, response_mime_type=mime_type, response_schema=schema)
            return {"response": follow_up_response.text}

        tx = self.blockchain.create_send_flr_tx(
            to_address=send_token_json.get("to_address"),
            amount=send_token_json.get("amount"),
        )
        self.logger.debug("send_token_tx", tx=tx)
        self.blockchain.add_tx_to_queue(msg=message, tx=tx)
        formatted_preview = (
            "Transaction Preview: "
            + f"Sending {Web3.from_wei(tx.get('value', 0), 'ether')} "
            + f"FLR to {tx.get('to')}\nType CONFIRM to proceed."
        )
        return {"response": formatted_preview}

    async def handle_check_balance(self, _: str) -> dict[str, str]:
        """
        Handle balance check requests with USD value conversion.

        Args:
            _: Unused message parameter

        Returns:
            dict[str, str]: Response containing balance information in FLR and USD
        """
        if not self.blockchain.address:
            return {"response": "No account exists. Please create an account first with 'Create an account for me'."}
            
        # Get all token balances with USD values
        token_balances = self.blockchain.get_token_balances_with_usd()
        
        # Format the response
        response_lines = ["Your current balances:"]
        
        for token, (amount, usd_value) in token_balances.items():
            usd_display = f"(${usd_value:.2f})" if usd_value is not None else "(USD value unavailable)"
            response_lines.append(f"{amount:.6f} {token} {usd_display}")
            
        # Add price information
        flr_price, timestamp = self.blockchain.ftso_feed.get_price("FLR")
        if flr_price is not None:
            response_lines.append(f"\nCurrent FLR price: ${flr_price:.4f} USD")
            response_lines.append(f"Price data timestamp: {timestamp}")
        
        return {"response": "\n".join(response_lines)}

    async def handle_swap_token(self, message: str) -> dict[str, str]:
        """
        Handle token swap requests.

        Args:
            message: Message containing token swap details

        Returns:
            dict[str, str]: Response containing transaction preview or follow-up prompt
        """

        if not self.blockchain.address:
            return {"response": "No account exists. Please create an account first with 'Create an account for me'."}

        prompt, mime_type, schema = self.prompts.get_formatted_prompt(
            "swap_token", user_input=message
        )
        swap_token_response = self.ai.generate(
            prompt=prompt, response_mime_type=mime_type, response_schema=schema
        )
        
        try:
            # Fix any trailing commas that might cause JSON parse errors
            fixed_json_text = swap_token_response.text.replace(",\n  }", "\n  }")
            swap_token_json = json.loads(fixed_json_text)
            
            # Check for all required fields
            has_from_token = "from_token" in swap_token_json
            has_to_token = "to_token" in swap_token_json
            has_amount = "amount" in swap_token_json and swap_token_json.get("amount") != 0.0
            
            # If we have both tokens but no amount, add a default amount of 1.0
            if has_from_token and has_to_token and not has_amount:
                self.logger.debug(
                    "swap_token_adding_default_amount",
                    from_token=swap_token_json.get("from_token"),
                    to_token=swap_token_json.get("to_token")
                )
                swap_token_json["amount"] = 1.0
                has_amount = True
            
            # Check if tokens are the same
            tokens_are_different = (
                has_from_token and 
                has_to_token and 
                swap_token_json.get("from_token") != swap_token_json.get("to_token")
            )
            
            if not (has_amount and has_from_token and has_to_token and tokens_are_different):
                self.logger.debug(
                    "swap_token_validation_failed", 
                    response_json=swap_token_response.text,
                    fixed_json=fixed_json_text,
                    has_amount=has_amount,
                    has_from_token=has_from_token,
                    has_to_token=has_to_token,
                    tokens_are_different=tokens_are_different
                )
                
                # Request more details with the follow-up prompt
                prompt, mime_type, schema = self.prompts.get_formatted_prompt("follow_up_token_send")
                follow_up_response = self.ai.generate(prompt=prompt, response_mime_type=mime_type, response_schema=schema)
                return {"response": follow_up_response.text}
            
        except (json.JSONDecodeError, KeyError) as e:
            self.logger.error("swap_token_json_error", error=str(e), response=swap_token_response.text)
            # Try to extract tokens from the failed JSON response using regex
            import re
            from_token_match = re.search(r'"from_token":\s*"([^"]+)"', swap_token_response.text)
            to_token_match = re.search(r'"to_token":\s*"([^"]+)"', swap_token_response.text)
            
            # If both tokens are found in the failed JSON, try to construct a valid JSON
            if from_token_match and to_token_match:
                from_token = from_token_match.group(1)
                to_token = to_token_match.group(1)
                
                # Only proceed if tokens are different
                if from_token != to_token:
                    self.logger.debug(
                        "swap_token_recovered_from_invalid_json",
                        from_token=from_token,
                        to_token=to_token
                    )
                    swap_token_json = {
                        "from_token": from_token,
                        "to_token": to_token,
                        "amount": 1.0  # Default amount
                    }
                    
                    # Skip to transaction creation
                    return await self._create_swap_transaction(message, swap_token_json)
            
            # If recovery failed, ask for more details
            prompt, mime_type, schema = self.prompts.get_formatted_prompt("follow_up_token_send")
            follow_up_response = self.ai.generate(prompt=prompt, response_mime_type=mime_type, response_schema=schema)
            return {"response": follow_up_response.text}

        # All validation passed, create the transaction
        return await self._create_swap_transaction(message, swap_token_json)
    
    async def _create_swap_transaction(self, message: str, swap_token_json: dict) -> dict[str, str]:
        """
        Helper method to create a swap transaction.
        
        Args:
            message: Original user message
            swap_token_json: Validated JSON with swap parameters
            
        Returns:
            dict[str, str]: Response containing transaction preview or error
        """
        try:
            # Get token details from validated JSON
            from_token = swap_token_json.get("from_token")
            to_token = swap_token_json.get("to_token")
            amount = swap_token_json.get("amount")
            
            # Clear any existing transactions in the queue to avoid duplicates
            self.blockchain.tx_queue.clear()
            
            # Default to V3 swap but could be configurable
            transactions = self.defi.create_swap_tx(
                from_token=from_token,
                to_token=to_token,
                amount=amount,
                sender=self.blockchain.address,
            )

            # Check if we got transactions back
            if not transactions:
                self.logger.error("swap_token_no_transactions")
                return {"response": f"Unable to create swap transaction for {amount} {from_token} to {to_token}."}
                
            # Handle special case for FLR->any token which returns 3 transactions: [wrap_tx, approve_tx, swap_tx]
            is_flr_wrap_flow = from_token.upper() == "FLR" and len(transactions) == 3
            
            if is_flr_wrap_flow:
                # For FLR source with wrapping: [wrap_tx, approve_tx, swap_tx]
                wrap_tx = transactions[0]
                approve_tx = transactions[1]
                swap_tx = transactions[2]
                
                # First, queue the wrap transaction
                self.logger.debug("wrap_flr_to_wflr", wrap_tx=wrap_tx)
                self.blockchain.add_tx_to_queue(msg=f"Wrap {amount} FLR to WFLR", tx=wrap_tx)
                
                # Then queue the approval (will be executed after wrap)
                self.logger.debug("approve_wflr_for_swap", approve_tx=approve_tx)
                self.blockchain.add_tx_to_queue(msg=f"Approve WFLR for swap", tx=approve_tx)
                
                # Finally, queue the swap
                self.logger.debug("swap_wflr_to_token", swap_tx=swap_tx)
                self.blockchain.add_tx_to_queue(msg=f"Swap WFLR to {to_token}", tx=swap_tx)
                
                return {"response": f"I've prepared the complete swap from {amount} {from_token} to {to_token}. This requires three steps: wrapping FLR to WFLR, approving WFLR for the router, and executing the swap. Type CONFIRM to proceed with these transactions."}
            elif len(transactions) == 2:
                # For non-FLR source with approval: [approval_tx, swap_tx]
                approval_tx = transactions[0]
                swap_tx = transactions[1]
                
                # Handle approval if needed
                self.logger.debug("swap_token_approval_needed", approval_tx=approval_tx)
                self.blockchain.add_tx_to_queue(msg=f"Approve {from_token} for swap", tx=approval_tx)
                
                # Queue the swap transaction (will be executed after approval)
                self.logger.debug("swap_token_tx", tx=swap_tx)
                self.blockchain.add_tx_to_queue(msg=f"Swap {amount} {from_token} to {to_token}", tx=swap_tx)
                
                return {"response": f"You need to approve {from_token} for trading first, then we'll swap {amount} {from_token} to {to_token}. Type CONFIRM to proceed with both transactions."}
            elif len(transactions) == 1:
                # For tokens that don't need approval: [swap_tx]
                swap_tx = transactions[0]
                
                # Process the swap transaction
                self.logger.debug("swap_token_tx", tx=swap_tx)
                self.blockchain.add_tx_to_queue(msg=f"Swap {amount} {from_token} to {to_token}", tx=swap_tx)
                
                return {"response": f"I'll swap {amount} {from_token} to {to_token}. Type CONFIRM to proceed with the swap transaction."}
            else:
                # Unexpected number of transactions
                self.logger.error("swap_token_unexpected_tx_count", count=len(transactions))
                return {"response": f"Unable to create swap transaction for {amount} {from_token} to {to_token} (unexpected transaction format)."}
                
        except Exception as e:
            self.logger.exception("swap_token_failed", error=str(e))
            return {"response": f"Failed to create swap transaction: {e!s}"}

    async def handle_add_liquidity(self, message: str) -> dict[str, str]:
        """
        Handle add liquidity requests.

        Args:
            message: Message containing add liquidity details

        Returns:
            dict[str, str]: Response containing transaction preview or follow-up prompt
        """
        if not self.blockchain.address:
            return {"response": "No account exists. Please create an account first with 'Create an account for me'."}

        prompt, mime_type, schema = self.prompts.get_formatted_prompt(
            "add_liquidity", user_input=message
        )
        add_liquidity_response = self.ai.generate(
            prompt=prompt, response_mime_type=mime_type, response_schema=schema
        )
        
        try:
            add_liquidity_json = json.loads(add_liquidity_response.text)
            
            # Check for all required fields
            expected_json_len = 4
            has_token_a = "token_a" in add_liquidity_json
            has_token_b = "token_b" in add_liquidity_json
            has_amount_a = "amount_a" in add_liquidity_json and add_liquidity_json.get("amount_a") != 0.0
            has_amount_b = "amount_b" in add_liquidity_json and add_liquidity_json.get("amount_b") != 0.0
            
            # Check if tokens are the same
            tokens_are_different = (
                has_token_a and 
                has_token_b and 
                add_liquidity_json.get("token_a") != add_liquidity_json.get("token_b")
            )
            
            if not (has_token_a and has_token_b and has_amount_a and has_amount_b and tokens_are_different):
                self.logger.debug(
                    "add_liquidity_validation_failed", 
                    response_json=add_liquidity_response.text,
                    has_token_a=has_token_a,
                    has_token_b=has_token_b,
                    has_amount_a=has_amount_a,
                    has_amount_b=has_amount_b,
                    tokens_are_different=tokens_are_different
                )
                
                # Request more details with the follow-up prompt
                prompt, mime_type, schema = self.prompts.get_formatted_prompt("follow_up_token_send")
                follow_up_response = self.ai.generate(prompt=prompt, response_mime_type=mime_type, response_schema=schema)
                return {"response": follow_up_response.text}
                
        except (json.JSONDecodeError, KeyError) as e:
            self.logger.error("add_liquidity_json_error", error=str(e), response=add_liquidity_response.text)
            # Request more details with the follow-up prompt
            prompt, mime_type, schema = self.prompts.get_formatted_prompt("follow_up_token_send")
            follow_up_response = self.ai.generate(prompt=prompt, response_mime_type=mime_type, response_schema=schema)
            return {"response": follow_up_response.text}

        # Use the DeFiService to create an add liquidity transaction
        try:
            # Extract details
            token_a = add_liquidity_json.get("token_a")
            token_b = add_liquidity_json.get("token_b")
            amount_a = add_liquidity_json.get("amount_a")
            amount_b = add_liquidity_json.get("amount_b")
            
            # Default to V3 liquidity but could be configurable
            tx, approval_txs = self.defi.create_add_liquidity_tx(
                token_a=token_a,
                token_b=token_b,
                amount_a=amount_a,
                amount_b=amount_b,
                sender=self.blockchain.address,
                use_v3=True,  # Could be a setting or user preference
            )

            # Handle approvals if needed
            if approval_txs:
                self.logger.debug("add_liquidity_approvals_needed", approval_txs=approval_txs)
                
                # Add the first approval to the queue
                approval_tx = approval_txs[0]
                approval_token = token_a if approval_tx['to'] == self.defi._get_token_address(token_a) else token_b
                self.blockchain.add_tx_to_queue(msg=f"Approve {approval_token} for liquidity", tx=approval_tx)
                
                return {"response": f"You need to approve {approval_token} for trading first. Type CONFIRM to proceed with the approval transaction."}

            self.logger.debug("add_liquidity_tx", tx=tx)
            self.blockchain.add_tx_to_queue(msg=message, tx=tx)

            # Create a formatted preview for the user
            formatted_preview = (
                f"Transaction Preview: Adding liquidity with {amount_a} {token_a} and {amount_b} {token_b}\n"
                f"Type CONFIRM to proceed."
            )

            return {"response": formatted_preview}
        except Exception as e:
            self.logger.exception("add_liquidity_failed", error=str(e))
            return {"response": f"Failed to create add liquidity transaction: {e!s}"}

    async def handle_attestation(self, _: str) -> dict[str, str]:
        """
        Handle attestation requests.

        Args:
            _: Unused message parameter

        Returns:
            dict[str, str]: Response containing attestation request
        """
        prompt = self.prompts.get_formatted_prompt("request_attestation")[0]
        request_attestation_response = self.ai.generate(prompt=prompt)
        self.attestation.attestation_requested = True
        return {"response": request_attestation_response.text}

    async def handle_conversation(self, message: str) -> dict[str, str]:
        """
        Handle general conversation messages.

        Args:
            message: Message to process

        Returns:
            dict[str, str]: Response from AI provider
        """
        response = self.ai.send_message(message)
        return {"response": response.text}
        
    async def validate_transaction_before_sending(self, tx: dict) -> dict[str, str]:
        """
        Validate a transaction before sending it to the blockchain.
        
        Args:
            tx: Transaction dictionary to validate
            
        Returns:
            A dictionary with validation status and details
        """
        if not self.transaction_validator:
            # If no validator is available, allow the transaction
            return {"is_valid": True, "risk_level": "unknown", "message": "Transaction validation not available"}
            
        try:
            # Validate the transaction using the SecureTransactionValidator
            result = await self.transaction_validator.validate_transaction(
                tx=tx,
                sender_address=self.blockchain.address,
            )
            
            # Create a user-friendly message based on the validation result
            if result.risk_level == TransactionRisk.CRITICAL:
                message = f"⚠️ CRITICAL RISK: This transaction was blocked for your safety. {result.recommendation}"
                return {"is_valid": False, "risk_level": result.risk_level.value, "message": message, "warnings": result.warnings}
                
            elif result.risk_level == TransactionRisk.HIGH:
                # Only show warning but allow HIGH risk transactions to proceed
                message = f"⚠️ HIGH RISK: This transaction is potentially dangerous. HIGH RISK DETECTED. Transaction should be carefully reviewed before proceeding.\nWarnings: {', '.join(result.warnings[:3]) if result.warnings else ''}"
                return {"is_valid": True, "risk_level": result.risk_level.value, "message": message, "warnings": result.warnings}
                
            elif result.risk_level == TransactionRisk.MEDIUM:
                message = f"⚠️ MEDIUM RISK: Exercise caution with this transaction. {result.recommendation}"
                return {"is_valid": True, "risk_level": result.risk_level.value, "message": message, "warnings": result.warnings}
                
            elif result.risk_level == TransactionRisk.LOW:
                message = f"ℹ️ LOW RISK: Transaction appears mostly safe. {result.recommendation}"
                return {"is_valid": True, "risk_level": result.risk_level.value, "message": message}
                
            else:  # SAFE
                message = "✅ SAFE: Transaction has passed all security checks."
                return {"is_valid": True, "risk_level": result.risk_level.value, "message": message}
                
        except Exception as e:
            self.logger.exception("transaction_validation_failed", error=str(e))
            # If validation fails, allow the transaction but warn the user
            return {
                "is_valid": True, 
                "risk_level": "unknown", 
                "message": f"Transaction validation failed: {str(e)}. Proceed with caution."
            }
