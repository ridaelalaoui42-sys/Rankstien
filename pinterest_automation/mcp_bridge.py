import asyncio
import logging
import os
import subprocess
from pathlib import Path

from backend.core.config import get_settings
from backend.core.engine import resolve_gemini_cli

from .config import normalize_board_name
from .mcp_client import get_mcp_client

logger = logging.getLogger("rankstein.mcp_bridge")


def publish_pin_agentic(image_path, title, description, link, board_name="Aperitivos", model=None):
    """
    Delegates the pinning task to an AI agent equipped with Playwright MCP tools.
    This is the 'high-reliability' method that handles UI changes and stale locks automatically.

    NOTE: This is a SYNC function — it blocks. Call publish_pin_agentic_async() from
    async contexts to avoid stalling the event loop.
    """
    image_abs = str(Path(image_path).resolve())
    board_name = normalize_board_name(board_name)

    # We still use the gemini CLI agent as the primary 'reasoner' because it can
    # dynamically react to the page state. However, we ensure it's using the
    # playwright-mcp server as its tool backend.

    prompt = f"""
Task: Publish a Pin to Pinterest using the configured Playwright MCP browser session.
- Image: {image_abs}
- Title: {title}
- Description: {description}
- Link: {link}
- Board: {board_name}

Instructions:
1. Use Playwright MCP tools only; do not ask for, print, or expose Google/Gemini API keys.
2. Navigate to https://www.pinterest.com/pin-creation-tool/
3. If not logged in, return an error that the configured local session is inactive.
4. Upload the image.
5. Fill in the title, description, and destination link.
6. Select the board '{board_name}'.
7. Click 'Publish'.
8. Verify the pin was created and find the resulting Pin URL.
9. Return ONLY the Pin URL on success, or a concise error message on failure.
10. Never expose cookies, browser profile paths, credentials, or secrets.
"""

    logger.info(f"Invoking agentic pinner for: {title}")

    try:
        settings = get_settings()
        gemini_path = resolve_gemini_cli(settings.gemini_cli_path)
        if not gemini_path:
            logger.error("Gemini CLI ('gemini') not found in PATH")
            return {"success": False, "error": "Gemini CLI not found"}

        model_name = model or settings.adk_model
        cmd = [gemini_path, "-p", prompt, "--model", model_name]
        if settings.gemini_cli_yolo:
            cmd.append("--yolo")
        env = os.environ.copy()
        if env.get("GEMINI_API_KEY") and not env.get("GOOGLE_API_KEY"):
            env["GOOGLE_API_KEY"] = env["GEMINI_API_KEY"]
        elif env.get("GOOGLE_API_KEY") and not env.get("GEMINI_API_KEY"):
            env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=settings.gemini_cli_timeout_seconds,
        )

        if result.returncode != 0:
            logger.error(f"Agentic pinner failed: {result.stderr}")
            return {"success": False, "error": result.stderr}

        output = result.stdout
        # Extract Pin URL from output
        import re

        match = re.search(r"https?://(?:www\.)?pinterest\.(?:com|[a-z]{2,3})/pin/\d+/?", output)
        if match:
            pin_url = match.group(0)
            logger.info(f"Agentic pinner SUCCESS: {pin_url}")
            return {"success": True, "pin_url": pin_url}
        else:
            logger.warning(f"Agentic pinner finished but no Pin URL found in output: {output}")
            return {"success": False, "error": "No Pin URL found in agent output", "output": output}

    except Exception as e:
        logger.error(f"Exception in agentic pinner: {e}")
        return {"success": False, "error": str(e)}


async def publish_pin_agentic_async(
    image_path, title, description, link, board_name="Aperitivos", model=None
):
    """
    Async-safe wrapper for publish_pin_agentic.

    The underlying Gemini CLI call is blocking (subprocess.run with up to 300s timeout).
    Running it directly in an async function would stall the entire event loop and block all
    other coroutines for the duration. This wrapper offloads it to a thread via asyncio.to_thread()
    so the supervisor's queue workers and health reporter keep running normally.
    """
    return await asyncio.to_thread(
        publish_pin_agentic, image_path, title, description, link, board_name, model
    )


async def publish_pin_direct_mcp(image_path, title, description, link, board_name="Aperitivos"):
    """
    Directly execute pinning using MCP tools without a full LLM agent loop.
    Faster but less resilient than publish_pin_agentic.
    """
    board_name = normalize_board_name(board_name)
    try:
        from backend.scripts.pinterest_batch_core import (
            close_turbo_browser,
            create_pin_from_fields,
            create_turbo_browser,
            ensure_account_logged_in,
            ensure_account_sessions,
            filter_available_accounts,
            load_accounts,
        )

        accounts = load_accounts()
        ensure_account_sessions(accounts)
        accounts = filter_available_accounts(accounts)
        if accounts:
            account = accounts[0]
            pw = context = page = None
            try:
                pw, context, page = await create_turbo_browser(
                    account, f"direct_mcp-{account.name}", headless=True
                )
                if await ensure_account_logged_in(page, account):
                    pin_id = await create_pin_from_fields(
                        page,
                        image_path,
                        title,
                        link,
                        description,
                        board_name,
                        f"direct_mcp-{account.name}",
                    )
                    if pin_id:
                        pin_url = f"https://www.pinterest.com/pin/{pin_id}/"
                        logger.info(f"Direct MCP shared-core SUCCESS: {pin_url}")
                        return {
                            "success": True,
                            "pin_url": pin_url,
                            "pin_id": pin_id,
                            "method": "shared-core",
                        }
            finally:
                await close_turbo_browser(pw, context)
    except Exception as shared_exc:
        logger.warning(f"Direct MCP shared-core path failed; using browser MCP fallback: {shared_exc}")

    client = get_mcp_client()
    try:
        await client.connect()
        image_abs = str(Path(image_path).resolve())

        logger.info(f"Direct MCP: Creating pin '{title}'...")
        # 1. Navigate
        await client.call_tool("browser_navigate", {"url": "https://www.pinterest.com/pin-creation-tool/"})
        await asyncio.sleep(5)

        # 2. Check login state via snapshot
        snapshot = await client.call_tool("browser_snapshot", {})
        # Note: snapshot usually returns a markdown string or a structured object depending on the client.
        # Standard playwright-mcp returns it as 'content' in result.
        content = str(snapshot.get("content", ""))
        if "login" in content.lower() or "log in" in content.lower():
            # Double check URL via evaluate
            url_res = await client.call_tool("browser_evaluate", {"function": "() => window.location.href"})
            current_url = str(url_res.get("result", ""))
            if "login" in current_url.lower():
                logger.error(f"Direct MCP: Not logged in. URL: {current_url}")
                return {"success": False, "error": "Not logged in"}

        # 3. Upload Image
        logger.info("Direct MCP: Uploading image...")
        await client.call_tool("browser_type", {"target": "input[type='file']", "text": image_abs})
        await asyncio.sleep(5)

        # 4. Fill Metadata
        logger.info("Direct MCP: Filling metadata...")
        await client.call_tool(
            "browser_fill_form",
            {
                "fields": [
                    {"target": 'input[id*="title" i], input[placeholder*="title" i]', "value": title[:100]},
                    {
                        "target": 'textarea[id*="description" i], textarea[placeholder*="description" i]',
                        "value": description[:500],
                    },
                    {"target": 'input[id*="link" i], input[placeholder*="link" i]', "value": link},
                ]
            },
        )

        # 5. Select Board
        if board_name:
            logger.info(f"Direct MCP: Selecting board '{board_name}'...")
            await client.call_tool(
                "browser_click",
                {"target": '[data-test-id="board-dropdown-select-button"], button[aria-label*="board" i]'},
            )
            await asyncio.sleep(2)
            await client.call_tool(
                "browser_type",
                {
                    "target": 'input[placeholder*="search" i], input[aria-label*="search" i]',
                    "text": board_name,
                },
            )
            await asyncio.sleep(2)
            # Use a slightly more flexible selector for the board row
            await client.call_tool(
                "browser_click",
                {
                    "target": f'div[data-test-id="board-row"]:has-text("{board_name}"), div[role="option"]:has-text("{board_name}"), div[data-test-id="board-row"]'
                },
            )
            await asyncio.sleep(1)

        # 6. Publish
        logger.info("Direct MCP: Clicking publish...")
        await client.call_tool(
            "browser_click",
            {
                "target": 'button[data-test-id="board-dropdown-save-button"], button:has-text("Publish"), button:has-text("Publicar")'
            },
        )

        # 7. Verification Loop
        logger.info("Direct MCP: Verifying success...")
        for i in range(12):  # Wait up to 60s (Pinterest can be slow)
            await asyncio.sleep(5)
            # Check URL
            url_res = await client.call_tool("browser_evaluate", {"function": "() => window.location.href"})
            url = str(url_res.get("result", ""))

            if "/pin/" in url and "pin-creation-tool" not in url:
                pin_id = url.split("/pin/")[-1].strip("/")
                logger.info(f"Direct MCP SUCCESS (URL): {url}")
                return {"success": True, "pin_url": url, "pin_id": pin_id}

            # Check for success toast or link in snapshot
            snap = await client.call_tool("browser_snapshot", {})
            snap_text = str(snap.get("content", ""))
            if "See your Pin" in snap_text or "Ver tu Pin" in snap_text:
                # Try to extract URL from snapshot text if possible, or just evaluate
                logger.info("Direct MCP: Success marker found in snapshot.")
                # We'll do one more check for the URL as it usually updates
                await asyncio.sleep(2)
                url_res = await client.call_tool(
                    "browser_evaluate", {"function": "() => window.location.href"}
                )
                url = str(url_res.get("result", ""))
                if "/pin/" in url:
                    pin_id = url.split("/pin/")[-1].strip("/")
                    return {"success": True, "pin_url": url, "pin_id": pin_id}
                return {"success": True, "message": "Success marker found but URL didn't update yet"}

        return {"success": True, "message": "Direct MCP sequence completed, but verification timed out"}

    except Exception as e:
        logger.error(f"Direct MCP failure: {e}")
        return {"success": False, "error": str(e)}
