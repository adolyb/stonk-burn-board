"""HTTP clients for the StonkFun public API and a Solana RPC node."""

import time

import requests

from . import config


class ApiError(RuntimeError):
  """Raised when an endpoint keeps failing after retries."""


class StonkFunClient:
  """Thin wrapper that respects the documented 300/min per-IP budget."""

  def __init__(self, base_url=None, timeout=None):
    self.base_url = (base_url or config.API_BASE).rstrip("/")
    self.timeout = timeout or config.HTTP_TIMEOUT
    self.session = requests.Session()
    self.session.headers.update({
      "User-Agent": config.USER_AGENT,
      "Accept": "application/json",
    })
    self.rate_limit_remaining = None

  def get(self, path, params=None, max_retries=3):
    url = f"{self.base_url}/{path.lstrip('/')}"
    for attempt in range(max_retries):
      response = self.session.get(url, params=params, timeout=self.timeout)
      remaining = response.headers.get("X-RateLimit-Remaining")
      if remaining is not None:
        self.rate_limit_remaining = int(remaining)

      if response.status_code == 429:
        # The server states how long to wait; honour it rather than guessing.
        time.sleep(float(response.headers.get("Retry-After", 2 ** attempt)))
        continue

      if response.status_code >= 500 and attempt < max_retries - 1:
        time.sleep(2 ** attempt)
        continue

      if not response.ok:
        raise ApiError(f"GET {url} -> {response.status_code} {response.text[:200]}")

      payload = response.json()
      if "error" in payload:
        raise ApiError(f"GET {url} -> {payload['error']}")
      return payload

    raise ApiError(f"GET {url} exhausted {max_retries} attempts (rate limited)")

  def token(self, mint):
    return self.get(f"tokens/{mint}")

  def burns(self, mint, limit=config.LIST_LIMIT):
    return self.get(f"tokens/{mint}/burns", params={"limit": limit})

  def revenue(self, limit=config.LIST_LIMIT):
    return self.get("revenue", params={"limit": limit})

  def revenue_history(self):
    return self.get("revenue/history")

  def stats(self):
    return self.get("stats")


def get_token_supply(mint, rpc_url=None, timeout=None):
  """Read the mint's current supply straight from a Solana RPC node.

  Returns the raw integer amount plus the slot it was observed at: the slot is
  what makes a later API-versus-chain comparison auditable.
  """
  rpc_url = rpc_url or config.RPC_URL
  body = {"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]}
  response = requests.post(
    rpc_url,
    json=body,
    timeout=timeout or config.HTTP_TIMEOUT,
    headers={"User-Agent": config.USER_AGENT},
  )
  response.raise_for_status()
  payload = response.json()
  if "error" in payload:
    raise ApiError(f"RPC getTokenSupply -> {payload['error']}")

  result = payload["result"]
  return {
    "rpcUrl": rpc_url,
    "slot": result["context"]["slot"],
    "amountRaw": result["value"]["amount"],
    "decimals": result["value"]["decimals"],
  }
