/**
 * WebSocket client with auto-reconnect.
 * Dispatches custom events on the window for each message type.
 */

const RECONNECT_DELAY = 2000;

class WsClient {
  constructor() {
    this._ws = null;
    this._connected = false;
    this._reconnectTimer = null;
  }

  get connected() {
    return this._connected;
  }

  connect() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws`;

    try {
      this._ws = new WebSocket(url);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._connected = true;
      window.dispatchEvent(new CustomEvent("ws-connected"));
    };

    this._ws.onclose = () => {
      this._connected = false;
      window.dispatchEvent(new CustomEvent("ws-disconnected"));
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      this._ws?.close();
    };

    this._ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        window.dispatchEvent(
          new CustomEvent("ws-message", { detail: data })
        );
      } catch {
        // Ignore non-JSON messages
      }
    };
  }

  send(data) {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(data));
    }
  }

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, RECONNECT_DELAY);
  }
}

export const wsClient = new WsClient();
