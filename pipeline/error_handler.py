"""
Central error handler for the Data Funnel pipeline.
Handles retries, logging, alerting, and pipeline state tracking.
"""

import time
import json
import os
import traceback
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_ALERT_WEBHOOK")
MAX_RETRIES = 3
RETRY_BACKOFF = [10, 30, 60]  # seconds between retries

LOG_FILE = "pipeline/pipeline.log"


# ── Logging ──

def log(level: str, step: str, message: str, error: Exception = None):
    """
    Log a pipeline event to file and print to console.

    Args:
        level: INFO, WARNING, ERROR, SUCCESS
        step: Which pipeline step this is from
        message: Human readable message
        error: Optional exception object
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = {
        "timestamp": timestamp,
        "level": level,
        "step": step,
        "message": message,
        "error": str(error) if error else None
    }

    icons = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "SUCCESS": "✅"}
    icon = icons.get(level, "•")
    print(f"{icon} [{timestamp}] [{step}] {message}")
    if error:
        print(f"   Error: {error}")

    # Write to log file
    os.makedirs("pipeline", exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Retry logic ──

def with_retry(func, step: str, *args, **kwargs):
    """
    Execute a function with automatic retry on failure.
    Uses exponential backoff between retries.
    After max retries — sends alert and raises.

    Args:
        func: Function to execute
        step: Step name for logging
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of func if successful

    Raises:
        Exception if all retries exhausted
    """
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = func(*args, **kwargs)
            if attempt > 1:
                log("SUCCESS", step, f"Succeeded on attempt {attempt}")
            return result

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF[attempt - 1]
                log("WARNING", step,
                    f"Attempt {attempt}/{MAX_RETRIES} failed. "
                    f"Retrying in {wait}s...", e)
                time.sleep(wait)
            else:
                log("ERROR", step,
                    f"All {MAX_RETRIES} attempts failed.", e)
                send_alert(step, last_error)
                raise


# ── Slack alerting ──

def send_alert(step: str, error: Exception):
    """
    Send a Slack alert when the pipeline fails after all retries.
    Requires SLACK_ALERT_WEBHOOK in .env
    """
    if not SLACK_WEBHOOK_URL:
        log("WARNING", "alert",
            "No SLACK_ALERT_WEBHOOK set — skipping Slack alert")
        return

    try:
        import requests
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        payload = {
            "text": (
                f":rotating_light: *Data Funnel Pipeline Failed*\n"
                f"*Step:* {step}\n"
                f"*Error:* {str(error)}\n"
                f"*Time:* {timestamp}\n"
                f"*Action needed:* Check `pipeline/pipeline.log` for details"
            )
        }
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        log("INFO", "alert", "Slack alert sent successfully")
    except Exception as alert_error:
        log("WARNING", "alert",
            "Failed to send Slack alert", alert_error)


# ── Pipeline state tracking ──

STATE_FILE = "pipeline/pipeline_state.json"

STEPS = [
    "extract_orders",
    "extract_products",
    "extract_customers",
    "extract_inventory",
    "transform",
    "qa_checks",
    "load_fact_orders",
    "load_fact_order_lines",
    "load_dim_products",
    "load_dim_customers",
    "load_dim_stores",
]


def load_state() -> dict:
    """Load pipeline state from file."""
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(step: str, status: str):
    """
    Save the status of a pipeline step.
    status: 'completed' or 'failed'
    """
    state = load_state()
    state[step] = {
        "status": status,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }
    os.makedirs("pipeline", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_step_completed(step: str) -> bool:
    """Check if a step already completed successfully in this run."""
    state = load_state()
    return state.get(step, {}).get("status") == "completed"


def clear_state():
    """Clear pipeline state — called at the start of a fresh run."""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    log("INFO", "state", "Pipeline state cleared — starting fresh run")


def get_pipeline_decision(failed_step: str) -> str:
    """
    Decide whether to restart from scratch or continue from failure point.

    Rules:
    - Failed in extract → restart from scratch (nothing written yet)
    - Failed in transform → restart from scratch (no BigQuery writes yet)
    - Failed in load → continue from failed table only
    - Staging dirty → clear staging, retry that table only

    Returns: 'restart' or 'continue'
    """
    extract_steps = [
        "extract_orders", "extract_products",
        "extract_customers", "extract_inventory"
    ]
    transform_steps = ["transform", "qa_checks"]

    if failed_step in extract_steps or failed_step in transform_steps:
        log("INFO", "decision",
            f"Failure in {failed_step} → restarting from scratch")
        return "restart"
    else:
        log("INFO", "decision",
            f"Failure in {failed_step} → continuing from failure point")
        return "continue"