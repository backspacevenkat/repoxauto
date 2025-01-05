import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';

const WebSocketContext = createContext(null);

export function useWebSocket() {
  return useContext(WebSocketContext);
}

// Global singleton state
const globalState = {
  socket: null,
  cleanup: null,
  connectionCount: 0,
  connecting: false
};

export function WebSocketProvider({ children }) {
  const [socket, setSocket] = useState(globalState.socket);
  const [isConnected, setIsConnected] = useState(false);
  const [messageQueue, setMessageQueue] = useState([]);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const MAX_RECONNECT_ATTEMPTS = 5;
  const INITIAL_RECONNECT_DELAY = 1000;
  const MAX_CONNECTIONS = 3;
  const [connectionAttempts, setConnectionAttempts] = useState(0);

  // Cleanup function for component unmount
  const cleanup = useCallback(() => {
    if (globalState.cleanup) {
      globalState.cleanup();
      globalState.cleanup = null;
    }
    if (globalState.socket) {
      try {
        globalState.socket.close(1000, 'Component unmounting');
      } catch (err) {
        console.error('Error closing socket:', err);
      }
      globalState.socket = null;
      globalState.connecting = false;
    }
    setSocket(null);
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    // Return if already connecting or connected, or if max connections reached
    if (globalState.connecting || (globalState.socket?.readyState === WebSocket.OPEN) || connectionAttempts >= MAX_CONNECTIONS) {
      if (globalState.socket?.readyState === WebSocket.OPEN) {
        setSocket(globalState.socket);
        setIsConnected(true);
      }
      return globalState.cleanup;
    }
    
    setConnectionAttempts(prev => prev + 1);

    // Set connecting flag and clear any existing state
    globalState.connecting = true;

    // Clear any existing socket and cleanup
    if (globalState.socket || globalState.cleanup) {
      try {
        if (globalState.cleanup) {
          globalState.cleanup();
        }
        if (globalState.socket?.readyState === WebSocket.OPEN) {
          globalState.socket.close(1000, 'Reconnecting');
        }
      } catch (err) {
        console.error('Error cleaning up existing connection:', err);
      }
      globalState.socket = null;
      globalState.cleanup = null;
      setSocket(null);
      setIsConnected(false);
    }
    if (globalState.socket) {
      try {
        globalState.socket.close(1000, 'Reconnecting');
      } catch (err) {
        console.error('Error closing existing socket:', err);
      }
    }
    if (globalState.cleanup) {
      try {
        globalState.cleanup();
      } catch (err) {
        console.error('Error in cleanup:', err);
      }
    }
    globalState.socket = null;
    globalState.cleanup = null;
    setSocket(null);
    setIsConnected(false);

    try {
      // Get WebSocket URL from environment or fallback
      const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:9000/ws';
      console.log('Connecting to WebSocket:', wsUrl);
      
      const ws = new WebSocket(wsUrl);
      
      // Set a connection timeout (increased to 20 seconds)
      const connectionTimeout = setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          console.log('Connection timeout - closing socket');
          ws.close(3000, 'Connection timeout');
        }
      }, 20000); // 20 second timeout

      ws.onopen = () => {
        console.log('WebSocket connected successfully');
        clearTimeout(connectionTimeout);
        setIsConnected(true);
        setReconnectAttempt(0);
        
        // Process any queued messages
        if (messageQueue.length > 0) {
          messageQueue.forEach(msg => {
            try {
              ws.send(JSON.stringify(msg));
            } catch (err) {
              console.error('Error sending queued message:', err);
            }
          });
          setMessageQueue([]);
        }

        // Send initial heartbeat
        try {
          ws.send(JSON.stringify({ type: 'heartbeat' }));
          console.log('Initial heartbeat sent');
        } catch (err) {
          console.error('Error sending initial heartbeat:', err);
        }
      };

      ws.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        setIsConnected(false);
        setSocket(null);

        // Attempt reconnection if not closing cleanly
        if (event.code !== 1000 && event.code !== 1001) {
          const shouldReconnect = reconnectAttempt < MAX_RECONNECT_ATTEMPTS;
          if (shouldReconnect) {
            const delay = Math.min(
              INITIAL_RECONNECT_DELAY * Math.pow(2, reconnectAttempt),
              30000
            );
            console.log(`Attempting to reconnect in ${delay}ms... (Attempt ${reconnectAttempt + 1}/${MAX_RECONNECT_ATTEMPTS})`);
            setTimeout(() => {
              setReconnectAttempt(prev => prev + 1);
              connect();
            }, delay);
          } else {
            console.log('Max reconnection attempts reached');
          }
        }
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        setIsConnected(false);
        // Trigger reconnect on error
        if (reconnectAttempt < MAX_RECONNECT_ATTEMPTS) {
          const delay = Math.min(INITIAL_RECONNECT_DELAY * Math.pow(2, reconnectAttempt), 30000);
          setTimeout(() => {
            setReconnectAttempt(prev => prev + 1);
            connect();
          }, delay);
        }
      };

      // Handle incoming messages including heartbeat responses
      let lastHeartbeatResponse = Date.now();
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'heartbeat_response') {
            console.log('Received heartbeat response');
            lastHeartbeatResponse = Date.now();
          } else if (data.type === 'connection_status' && data.status === 'connected') {
            console.log('Connection confirmed by server');
          } else {
            console.log('Received message:', data);
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      // Set up heartbeat interval with timeout check
      let heartbeatTimeout;
      const heartbeatInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          // Check if we've missed responses
          const timeSinceLastResponse = Date.now() - lastHeartbeatResponse;
          if (timeSinceLastResponse > 90000) { // 90 seconds without response
            console.log('No heartbeat response in 90s - reconnecting...');
            ws.close(3000, 'No heartbeat response');
            return;
          }
          
          // Clear previous timeout
          if (heartbeatTimeout) {
            clearTimeout(heartbeatTimeout);
          }
          
          try {
            // Send heartbeat
            ws.send(JSON.stringify({ type: 'heartbeat' }));
            console.log('Heartbeat sent');
            
            // Set timeout for response
            heartbeatTimeout = setTimeout(() => {
              console.log('Checking heartbeat response...');
              const timeSinceLastResponse = Date.now() - lastHeartbeatResponse;
              if (timeSinceLastResponse > 90000) {
                console.log('Heartbeat timeout after 90s - reconnecting...');
                ws.close(3000, 'Heartbeat timeout');
              }
            }, 50000); // Check after 50 seconds
          } catch (error) {
            console.error('Error sending heartbeat:', error);
            ws.close(3000, 'Heartbeat send error');
          }
        }
      }, 30000); // Send heartbeat every 30 seconds

      // Clean up heartbeat and timeout on unmount
      const cleanup = () => {
        clearTimeout(connectionTimeout);
        if (heartbeatTimeout) {
          clearTimeout(heartbeatTimeout);
        }
        clearInterval(heartbeatInterval);
        if (ws.readyState === WebSocket.OPEN) {
          ws.close(1000, 'Component unmounting');
        }
      };

      globalState.socket = ws;
      globalState.cleanup = cleanup;
      globalState.connecting = false;
      setSocket(ws);
      return cleanup;
    } catch (error) {
      console.error('Error creating WebSocket:', error);
      setIsConnected(false);
      return () => {};
    }
  }, [messageQueue, reconnectAttempt]);

  // Connect on mount and handle reconnection
  useEffect(() => {
    let mounted = true;
    let connectionTimeout;
    let healthCheckInterval;

    const initConnection = async () => {
      if (!mounted) return;

      // Clear any existing timeouts/intervals
      if (connectionTimeout) {
        clearTimeout(connectionTimeout);
      }
      if (healthCheckInterval) {
        clearInterval(healthCheckInterval);
      }

      // Only connect if we don't have a valid connection
      if (!globalState.socket || globalState.socket.readyState === WebSocket.CLOSED) {
        connect();
      } else if (globalState.socket.readyState === WebSocket.OPEN) {
        setSocket(globalState.socket);
        setIsConnected(true);
      }

      // Set up health check interval - but only if we haven't exceeded max connections
      healthCheckInterval = setInterval(() => {
        if (mounted && (!globalState.socket || globalState.socket.readyState === WebSocket.CLOSED) && connectionAttempts < MAX_CONNECTIONS) {
          console.log('Health check - reconnecting...');
          connect();
        }
      }, 60000); // Check every 60 seconds
    };

    initConnection();

    return () => {
      mounted = false;
      if (connectionTimeout) {
        clearTimeout(connectionTimeout);
      }
      if (healthCheckInterval) {
        clearInterval(healthCheckInterval);
      }
      // Only cleanup if this is the last instance
      if (globalState.socket?.readyState === WebSocket.OPEN) {
        try {
          globalState.socket.close(1000, 'Component unmounting');
        } catch (err) {
          console.error('Error closing socket:', err);
        }
      }
    };
  }, [connect]);

  const sendMessage = useCallback((message) => {
    if (socket?.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify(message));
      } catch (err) {
        console.error('Error sending message:', err);
        setMessageQueue(prev => [...prev, message]);
      }
    } else {
      setMessageQueue(prev => [...prev, message]);
      if (!isConnected) {
        connect();
      }
    }
  }, [socket, isConnected, connect]);

  const value = {
    socket,
    isConnected,
    sendMessage
  };

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}
