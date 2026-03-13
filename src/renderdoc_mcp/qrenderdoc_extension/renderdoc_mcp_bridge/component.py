class BridgeComponent:
    def __init__(self, client) -> None:
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)

    def _call_bridge_client(self, method_name: str, *args, **kwargs):
        from .client import BridgeClient

        method = getattr(BridgeClient, method_name)
        return method(self.client, *args, **kwargs)
