class WebSocketService {
    constructor() {
        this.socket = null;
        this.isConnecting = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000;
        this.listeners = new Map();
        this.connectionPromise = null;
        this.stateListeners = new Set();
    }

    async connect() {
        if (this.isConnecting || this.socket?.readyState === WebSocket.CONNECTING) {
            return this.connectionPromise;
        }

        if (this.socket?.readyState === WebSocket.OPEN) {
            return Promise.resolve(this.socket);
        }

        this.isConnecting = true;
        this.notifyStateChange('connecting');
        
        this.connectionPromise = new Promise((resolve, reject) => {
            try {
                // Use environment variable for WebSocket URL
                const wsUrl = process.env.NEXT_PUBLIC_WS_URL;
                this.socket = new WebSocket(wsUrl);

                this.socket.onopen = () => {
                    console.log('WebSocket connected');
                    this.isConnecting = false;
                    this.reconnectAttempts = 0;
                    this.setupHeartbeat();
                    this.notifyStateChange('connected');
                    resolve(this.socket);
                };

                this.socket.onclose = (event) => {
                    console.log('WebSocket closed:', event.code, event.reason);
                    this.isConnecting = false;
                    this.notifyStateChange('disconnected');
                    this.handleReconnect();
                };

                this.socket.onerror = (error) => {
                    console.error('WebSocket error:', error);
                    this.isConnecting = false;
                    this.notifyStateChange('error');
                    reject(error);
                };

                this.socket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        this.handleMessage(data);
                    } catch (err) {
                        console.error('Error handling message:', err);
                    }
                };

            } catch (err) {
                this.isConnecting = false;
                this.notifyStateChange('error');
                reject(err);
            }
        });

        return this.connectionPromise;
    }

    setupHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
        }

        this.heartbeatInterval = setInterval(() => {
            if (this.socket?.readyState === WebSocket.OPEN) {
                this.socket.send(JSON.stringify({ type: 'pong' }));
            }
        }, 15000);
    }

    handleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
            this.reconnectAttempts++;
            
            // Notify all listeners about reconnection attempt
            this.notifyStateChange('reconnecting');
            
            console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            
            setTimeout(() => {
                this.connect().catch(err => {
                    console.error('Reconnection failed:', err);
                    this.notifyStateChange('error');
                });
            }, delay);
        } else {
            console.error('Max reconnection attempts reached');
            this.notifyStateChange('error');
        }
    }

    handleMessage(data) {
        if (data.type === 'ping') {
            this.socket?.send(JSON.stringify({ type: 'pong' }));
            return;
        }

        // Broadcast to all listeners of this type
        const listeners = this.listeners.get(data.type) || [];
        listeners.forEach(callback => {
            try {
                callback(data);
            } catch (err) {
                console.error('Error in message listener:', err);
            }
        });

        // Also broadcast to '*' listeners for all messages
        const globalListeners = this.listeners.get('*') || [];
        globalListeners.forEach(callback => {
            try {
                callback(data);
            } catch (err) {
                console.error('Error in global message listener:', err);
            }
        });
    }

    notifyStateChange(state) {
        this.stateListeners.forEach(listener => {
            try {
                listener({ state });
            } catch (err) {
                console.error('Error in state listener:', err);
            }
        });
    }

    subscribe(type, callback) {
        if (!this.listeners.has(type)) {
            this.listeners.set(type, []);
        }
        this.listeners.get(type).push(callback);

        // If subscribing to connection state updates
        if (type === 'connection_state') {
            this.stateListeners.add(callback);
            // Immediately notify of current state
            if (this.socket?.readyState === WebSocket.OPEN) {
                callback({ state: 'connected' });
            } else if (this.isConnecting) {
                callback({ state: 'connecting' });
            } else {
                callback({ state: 'disconnected' });
            }
        }
    }

    unsubscribe(type, callback) {
        if (type === 'connection_state') {
            this.stateListeners.delete(callback);
        }
        
        if (!this.listeners.has(type)) return;
        const listeners = this.listeners.get(type);
        const index = listeners.indexOf(callback);
        if (index > -1) {
            listeners.splice(index, 1);
        }
    }

    send(message) {
        if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(message));
            return true;
        }
        return false;
    }

    disconnect() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
        }
        if (this.socket) {
            this.socket.close(1000, 'Client disconnecting');
            this.socket = null;
        }
        this.isConnecting = false;
        this.listeners.clear();
        this.stateListeners.clear();
        this.notifyStateChange('disconnected');
    }
}

export const websocketService = new WebSocketService();
