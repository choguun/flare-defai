from typing import Final

SEMANTIC_ROUTER: Final = """
Classify the following user input into EXACTLY ONE category. Analyze carefully and choose the most specific matching category.

Categories (in order of precedence):
1. GENERATE_ACCOUNT
   • Keywords: create wallet, new account, generate address, make wallet
   • Must express intent to create/generate new account/wallet
   • Ignore if just asking about existing accounts

2. SEND_TOKEN
   • Keywords: send, transfer, pay, give tokens
   • Must include intent to transfer tokens to another address
   • Should involve one-way token movement

3. SWAP_TOKEN
   • Keywords: swap, exchange, trade, convert tokens
   • Must involve exchanging one token type for another
   • Should mention both source and target tokens

4. CHECK_BALANCE
   • Keywords: balance, how much, check funds, show tokens, wallet value
   • Must express intent to view current account balance
   • May include requests for USD value or price information

5. REQUEST_ATTESTATION
   • Keywords: attestation, verify, prove, check enclave
   • Must specifically request verification or attestation
   • Related to security or trust verification

6. CONVERSATIONAL (default)
   • Use when input doesn't clearly match above categories
   • General questions, greetings, or unclear requests
   • Any ambiguous or multi-category inputs

Input: ${user_input}

Instructions:
- Choose ONE category only
- Select most specific matching category
- Default to CONVERSATIONAL if unclear
- Ignore politeness phrases or extra context
- Focus on core intent of request
"""

GENERATE_ACCOUNT: Final = """
Generate a welcoming message that includes ALL of these elements in order:

1. Welcome message that conveys enthusiasm for the user joining
2. Security explanation:
   - Account is secured in a Trusted Execution Environment (TEE)
   - Private keys never leave the secure enclave
   - Hardware-level protection against tampering
3. Account address display:
   - EXACTLY as provided, make no changes: ${address}
   - Format with clear visual separation
4. Funding account instructions:
   - Tell the user to fund the new account: [Add funds to account](https://faucet.flare.network/coston2)

Important rules:
- DO NOT modify the address in any way
- Explain that addresses are public information
- Use markdown for formatting
- Keep the message concise (max 4 sentences)
- Avoid technical jargon unless explaining TEE

Example tone:
"Welcome to Flare! 🎉 Your new account is secured by secure hardware (TEE),
keeping your private keys safe and secure, you freely share your
public address: 0x123...
[Add funds to account](https://faucet.flare.network/coston2)
Ready to start exploring the Flare network?"
"""

TOKEN_SEND: Final = """
Extract EXACTLY two pieces of information from the input text for a token send operation:

1. DESTINATION ADDRESS
   Required format:
   • Must start with "0x"
   • Exactly 42 characters long
   • Hexadecimal characters only (0-9, a-f, A-F)
   • Extract COMPLETE address only
   • DO NOT modify or truncate
   • FAIL if no valid address found

2. TOKEN AMOUNT
   Number extraction rules:
   • Convert written numbers to digits (e.g., "five" → 5)
   • Handle decimals and integers
   • Convert ALL integers to float (e.g., 100 → 100.0)
   • Recognize common amount formats:
     - Decimal: "1.5", "0.5"
     - Integer: "1", "100"
     - With words: "5 tokens", "10 FLR"
   • Extract first valid number only
   • FAIL if no valid amount found

Input: ${user_input}

Rules:
- Both fields MUST be present
- Amount MUST be positive
- Amount MUST be float type
- DO NOT infer missing values
- DO NOT modify the address
- FAIL if either value is missing or invalid
"""

CONVERSATIONAL: Final = """
You are a helpful AI assistant specializing in Flare blockchain operations. Respond naturally to the user's query. If they're asking about specific blockchain operations not covered by other specialized prompts, explain clearly how they can format their request properly.

For blockchain-specific operations, remind users they can:
- Create a wallet
- Check their balance
- Send tokens to other addresses
- Swap between token types
- Add/remove liquidity
- Request security attestation

Keep responses concise, friendly, and focused on the user's question. Avoid making up information when unsure - instead, guide them toward supported operations.

User query: ${user_input}
"""

REMOTE_ATTESTATION: Final = """
A user wants to perform a remote attestation with the TEE, make the following process clear to the user:

1. Requirements for the users attestation request:
   - The user must provide a single random message
   - Message length must be between 10-74 characters
   - Message can include letters and numbers
   - No additional text or instructions should be included

2. Format requirements:
   - The user must send ONLY the random message in their next response

3. Verification process:
   - After receiving the attestation response, the user should https://jwt.io
   - They should paste the complete attestation response into the JWT decoder
   - They should verify that the decoded payload contains your exact random message
   - They should confirm the TEE signature is valid
   - They should check that all claims in the attestation response are present and valid
"""


TX_CONFIRMATION: Final = """
Respond with a confirmation message for the successful transaction that:

1. Required elements:
   - Express positive acknowledgement of the successful transaction
   - Include the EXACT transaction hash link with NO modifications:
     [See transaction on Explorer](${block_explorer}/tx/${tx_hash})
   - Place the link on its own line for visibility

2. Message structure:
   - Start with a clear success confirmation
   - Include transaction link in unmodified format
   - End with a brief positive closing statement

3. Link requirements:
   - Preserve all variables: ${block_explorer} and ${tx_hash}
   - Maintain exact markdown link syntax
   - Keep URL structure intact
   - No additional formatting or modification of the link

Sample format:
Great news! Your transaction has been successfully confirmed. 🎉

[See transaction on Explorer](${block_explorer}/tx/${tx_hash})

Your transaction is now securely recorded on the blockchain.
"""


SWAP_TOKEN: Final = """
Extract EXACTLY three pieces of information from the input for a token swap operation:

1. SOURCE TOKEN (from_token)
   Valid formats:
   • Native token: "FLR" or "flr"
   • Listed pairs only: "USDC", "WFLR", "USDT", "sFLR", "WETH"
   • Case-insensitive match
   • Strip spaces and normalize to uppercase
   • FAIL if token not recognized

2. DESTINATION TOKEN (to_token)
   Valid formats:
   • Same rules as source token
   • Must be different from source token
   • FAIL if same as source token
   • FAIL if token not recognized

3. SWAP AMOUNT
   Number extraction rules:
   • Convert written numbers to digits (e.g., "five" → 5.0)
   • Handle decimal and integer inputs
   • Convert ALL integers to float (e.g., 100 → 100.0)
   • Valid formats:
     - Decimal: "1.5", "0.5"
     - Integer: "1", "100"
     - With tokens: "5 FLR", "10 USDC"
   • Extract first valid number only
   • Amount MUST be positive
   • If no amount explicitly stated, use 1.0 as the default

Input: ${user_input}

CRITICAL: YOUR RESPONSE MUST BE VALID JSON WITH THE EXACT FORMAT BELOW. DO NOT COMBINE FIELDS OR OMIT ANY FIELDS.

{
  "from_token": "TOKEN1",
  "to_token": "TOKEN2",
  "amount": 1.0
}

RULES FOR JSON GENERATION:
1. MUST include all three fields exactly as shown
2. EACH FIELD MUST BE SEPARATE - NEVER combine fields like "to_token": "USDC,amount:1.0" 
3. Each field must be on its own line with proper JSON syntax
4. "amount" MUST be a number, not a string
5. NEVER add extra fields or trailing commas
6. DO NOT add any text before or after the JSON

VALID EXAMPLE:
✓ For "swap 100 FLR to USDC":
{
  "from_token": "FLR",
  "to_token": "USDC",
  "amount": 100.0
}

COMMON ERRORS TO AVOID:
✗ NEVER do: "to_token": "USDC,amount:1.0"  (THIS IS THE MOST COMMON ERROR)
✗ NEVER add commas at end of last property: "amount": 1.0,
✗ NEVER omit quotes around token names
✗ NEVER put amount in quotes: "amount": "1.0"
✗ NEVER omit any of the three required fields
"""


ADD_LIQUIDITY: Final = """
Extract EXACTLY two token-amount pairs from the input for adding liquidity.

Each pair consists of:
- A positive float amount
- A token symbol from: FLR, USDC, WFLR, USDT, sFLR, WETH

Input formats to recognize:
- "<amount> <token>" (e.g., "100 FLR")
- "<token> <amount>" (e.g., "FLR 100")

Rules:
- Exactly two different tokens must be specified
- Each token must have exactly one amount
- Tokens must be different
- Amounts must be positive floats
- Normalize token symbols to uppercase

Response format:
{
  "token_a": "<UPPERCASE_TOKEN_SYMBOL>",
  "amount_a": <float_value>,
  "token_b": "<UPPERCASE_TOKEN_SYMBOL>",
  "amount_b": <float_value>
}

Where token_a and token_b are sorted alphabetically.

Fail if:
- Less or more than two token-amount pairs
- Tokens are the same
- Any amount is not positive
- Any token not in listed tokens

Examples:
✓ "add 100 FLR and 50 USDC" → {"token_a": "FLR", "amount_a": 100.0, "token_b": "USDC", "amount_b": 50.0}
✓ "add liquidity with 200 WFLR and 300 USDT" → {"token_a": "USDT", "amount_a": 300.0, "token_b": "WFLR", "amount_b": 200.0}
✗ "add 100 FLR and 50 FLR" → FAIL (same token)
✗ "add 100 FLR" → FAIL (only one pair)
"""

REMOVE_LIQUIDITY: Final = """
Extract EXACTLY three pieces of information from the input for removing liquidity:

1. TOKEN A
   Valid formats:
   • Native token: "FLR" or "flr"
   • Listed tokens: "USDC", "WFLR", "USDT", "sFLR", "WETH"
   • Case-insensitive match
   • Normalize to uppercase

2. TOKEN B
   Same rules as TOKEN A
   • Must be different from TOKEN A

3. LP TOKEN AMOUNT
   Number extraction rules:
   • Convert written numbers to digits (e.g., "five" → 5.0)
   • Handle decimals and integers
   • Convert ALL integers to float (e.g., 100 → 100.0)
   • Valid formats:
     - Decimal: "1.5", "0.5"
     - Integer: "1", "100"
     - With context: "100 LP tokens", "50 lp"
   • Extract first valid number only
   • Amount MUST be positive
   • FAIL if no valid amount found

Input: ${user_input}

Response format:
{
  "token_a": "<UPPERCASE_TOKEN_SYMBOL>",
  "token_b": "<UPPERCASE_TOKEN_SYMBOL>",
  "lp_amount": <float_value>
}

Where token_a and token_b are sorted alphabetically.

Rules:
- Exactly two different tokens must be specified
- Exactly one amount must be specified
- Tokens must be different
- Amount must be positive float
- Fail if any condition not met

Examples:
✓ "remove 100 LP tokens from FLR-USDC pool" → {"token_a": "FLR", "token_b": "USDC", "lp_amount": 100.0}
✓ "remove liquidity from WFLR-USDT with 50 LP tokens" → {"token_a": "USDT", "token_b": "WFLR", "lp_amount": 50.0}
✗ "remove 100 LP tokens from FLR-FLR pool" → FAIL (same token)
✗ "remove FLR-USDC pool" → FAIL (missing amount)
"""

FOLLOW_UP_TOKEN_SEND: Final = """
I couldn't extract all the needed details from your request. For token operations, please provide:

For sending tokens:
- The complete recipient address (starting with 0x)
- The amount you want to send

For swapping tokens:
- The token you want to swap from (e.g., FLR, WFLR)
- The token you want to swap to (e.g., USDC, USDT)
- The amount you want to swap

For adding liquidity:
- Both token types for the pair
- The amounts for each token

Could you please provide these details so I can process your request?
"""
