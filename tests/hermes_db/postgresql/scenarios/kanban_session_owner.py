"""Production embedded session API for the narrower Kanban protocol contract.

The full gateway scenario remains mandatory after every domain is ported. No production
feature is patched; the session runtime's documented embedded entry points are composed here.
"""

import asyncio


async def main():
    from gateway.run import GatewayRunner
    from gateway.run_bootstrap import _start_gateway_start_control_socket
    from gateway.run_runtime import initialize_gateway_runtime, start_gateway_runtime_api, publish_gateway_runtime_ready
    from gateway.runtime_ownership import process_ownership
    from hermes_constants import get_hermes_home
    home = get_hermes_home()
    process_ownership.reserve([home], purpose="gateway")
    try:
        runner = GatewayRunner()
        await initialize_gateway_runtime(runner)
        control = await _start_gateway_start_control_socket(runner)
        assert control is not None
        await start_gateway_runtime_api(runner)
        runner._running = True
        publish_gateway_runtime_ready(runner)
        await asyncio.Event().wait()
    finally:
        process_ownership.release(home)


if __name__ == "__main__":
    asyncio.run(main())
