"""Inspect live API responses and status codes from CSFloat and Skinport."""

import asyncio

import httpx


async def inspect() -> None:
    headers = {
        "User-Agent": "CollectiblesMonitor/0.1.0 (Research & Pricing; +safe)",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        print("\n--- Inspecting CSFloat ---")
        try:
            resp_csfloat = await client.get(
                "https://csfloat.com/api/v1/listings", params={"limit": 3}
            )
            print(f"CSFloat Status Code: {resp_csfloat.status_code}")
            print(f"CSFloat Content-Type: {resp_csfloat.headers.get('content-type')}")
            print(f"CSFloat Preview: {resp_csfloat.text[:300]}")
        except Exception as e:
            print(f"CSFloat Error: {e}")

        print("\n--- Inspecting Skinport ---")
        try:
            skinport_headers = {
                "User-Agent": "CollectiblesMonitor/0.1.0",
                "Accept-Encoding": "br, gzip",
            }
            resp_skinport = await client.get(
                "https://api.skinport.com/v1/items",
                params={"app_id": 730, "currency": "USD"},
                headers=skinport_headers,
            )
            print(f"Skinport Status Code: {resp_skinport.status_code}")
            print(f"Skinport Content-Type: {resp_skinport.headers.get('content-type')}")
            print(f"Skinport Items Count: {len(resp_skinport.json())}")
            print(f"First item: {resp_skinport.json()[0]}")
        except Exception as e:
            print(f"Skinport Error: {e}")

        print("\n--- Inspecting Steam Market ---")
        try:
            resp_steam = await client.get(
                "https://steamcommunity.com/market/priceoverview/",
                params={
                    "appid": 730,
                    "currency": 1,
                    "market_hash_name": "AK-47 | Redline (Field-Tested)",
                },
            )
            print(f"Steam Status Code: {resp_steam.status_code}")
            print(f"Steam Response: {resp_steam.json()}")
        except Exception as e:
            print(f"Steam Error: {e}")


if __name__ == "__main__":
    asyncio.run(inspect())
