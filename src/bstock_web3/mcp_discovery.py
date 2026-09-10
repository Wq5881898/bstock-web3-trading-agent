"""Transport-independent MCP discovery. Deliberately exposes no tools/call."""


class DiscoveryClient:
    """exchange(message) returns a parsed JSON-RPC reply (None for notification).

    Transport/authentication belong to a separate adapter, not this class.
    Server tool descriptions are untrusted data, never execution instructions.
    """
    VERSION = "2025-11-25"

    def __init__(self, exchange):
        self._exchange = exchange
        self._next_id = 0
        self.ready = False

    def _request(self, method, params):
        if method not in ("initialize", "tools/list"):
            raise ValueError("Discovery-only client: method prohibited")
        self._next_id += 1
        request_id = self._next_id
        reply = self._exchange({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0" or type(reply.get("id")) is not int or reply["id"] != request_id:
            raise ValueError("Invalid MCP response envelope")
        if "error" in reply or not isinstance(reply.get("result"), dict):
            raise ValueError("MCP request failed")  # do not echo server-controlled error bodies
        return reply["result"]

    def initialize(self):
        if self.ready:
            raise ValueError("Already initialized")
        result = self._request("initialize", {"protocolVersion": self.VERSION, "capabilities": {},
            "clientInfo": {"name": "bstock-web3-discovery", "version": "1.1.0"}})
        if result.get("protocolVersion") != self.VERSION:
            raise ValueError("Unsupported negotiated protocol version")
        if not isinstance(result.get("capabilities"), dict) or not isinstance(result.get("serverInfo"), dict):
            raise ValueError("Invalid initialization result")
        if not isinstance(result["capabilities"].get("tools"), dict):
            raise ValueError("Server does not advertise tools discovery")
        self._exchange({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.ready = True
        return result

    def list_tools(self, max_pages=20):
        if not self.ready:
            raise ValueError("Initialize before listing tools")
        if type(max_pages) is not int or not 1 <= max_pages <= 100:
            raise ValueError("Invalid page bound")
        tools, names, cursors = [], set(), set()
        params = {}
        for _ in range(max_pages):
            result = self._request("tools/list", params)
            page = result.get("tools")
            if not isinstance(page, list) or len(tools) + len(page) > 10000:
                raise ValueError("Invalid or excessive tool list")
            for tool in page:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"] or not isinstance(tool.get("inputSchema"), dict):
                    raise ValueError("Invalid tool definition")
                if tool["name"] in names:
                    raise ValueError("Duplicate tool name")
                names.add(tool["name"])
                tools.append(tool)
            cursor = result.get("nextCursor")
            if cursor is None:
                return tools
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Invalid or repeated pagination cursor")
            cursors.add(cursor)
            params = {"cursor": cursor}
        raise ValueError("Tool pagination limit reached")
