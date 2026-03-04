import json
import requests
from config import log

# =============================================================================
# TOOL FUNCTIONS
# Add new tools here. Each tool is just a Python function.
# Then register it in TOOLS (the schema) and TOOL_FUNCTIONS (the dispatch map).
# =============================================================================

def get_temperature():
    """Fetches temperature and humidity from a Raspberry Pi sensor."""
    try:
        response = requests.get('http://192.168.1.249:5000/get-temp', timeout=30)
        data = response.json()
        return (
            f"The temperature is {data['temperature']} degrees Fahrenheit "
            f"with {data['humidity']}% humidity."
        )
    except Exception as e:
        return f"Error: Failed to communicate with the Raspberry Pi: {e}"


# Add more tool functions below, for example:
#
# def get_current_time():
#     from datetime import datetime
#     return f"The current time is {datetime.now().strftime('%I:%M %p')}."
#
# def store_player_note(note: str):
#     from memory import store_player_fact
#     store_player_fact(note)
#     return f"I'll remember that."


# =============================================================================
# TOOL SCHEMAS
# The JSON schema list passed to the API on every call.
# Each entry must have a matching entry in TOOL_FUNCTIONS below.
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_temperature",
            "description": (
                "Gets the current temperature and humidity from a DHT11 sensor "
                "connected to a Raspberry Pi. Use this when the player asks about "
                "the temperature or how warm or cold it is."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
]


# Maps tool names to their Python functions.
TOOL_FUNCTIONS = {
    "get_temperature": get_temperature,
}


# =============================================================================
# DISPATCH
# =============================================================================

def handle_tool_call(name: str, arguments: dict) -> str:
    """Dispatches a model tool call to the correct Python function."""
    if name in TOOL_FUNCTIONS:
        log(f"[TOOL] Executing '{name}' with args: {arguments}")
        result = TOOL_FUNCTIONS[name](**arguments)
        log(f"[TOOL] Result: {result}")
        return result
    return f"Error: unknown tool '{name}'"


def process_tool_calls(response_message, messages: list) -> list:
    """
    If the model returned tool calls, execute them all and append
    the results to the message list. Returns the updated list.
    """
    messages.append(response_message)

    for tool_call in response_message.tool_calls:
        name = tool_call.function.name
        arguments = json.loads(tool_call.function.arguments or "{}")
        result = handle_tool_call(name, arguments)

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(result)
        })

    return messages
