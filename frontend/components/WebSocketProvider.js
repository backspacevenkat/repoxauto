import React, { createContext, useContext, useEffect, useState, useRef } from 'react';
import { websocketService } from '../services/websocket.service';

const WebSocketContext = createContext(null);

export function useWebSocket() {
  return useContext(WebSocketContext);
}

// Connection states
const ConnectionState = {
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  RECONNECTING: 'reconnecting',
  ERROR: 'error'
};

export function WebSocketProvider({ children }) {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionState, setConnectionState] = useState('disconnected');
  const [socket, setSocket] = useState(null);
  const stateListenerRef = useRef(null);

  useEffect(() => {
    const connect = async () => {
      try {
        setConnectionState('connecting');
        const ws = await websocketService.connect();
        setSocket(ws);
        setIsConnected(true);
        setConnectionState('connected');
      } catch (err) {
        console.error('WebSocket connection error:', err);
        setConnectionState('error');
        setIsConnected(false);
      }
    };

    // Create state listener function and store in ref
    stateListenerRef.current = (data) => {
      console.log('WebSocket state change:', data.state);
      setConnectionState(data.state);
      setIsConnected(data.state === 'connected');
      
      // If disconnected, clear socket reference
      if (data.state === 'disconnected' || data.state === 'error') {
        setSocket(null);
      }
    };

    // Subscribe to connection state changes
    websocketService.subscribe('connection_state', stateListenerRef.current);

    // Initial connection
    connect();

    // Cleanup on unmount
    return () => {
      if (stateListenerRef.current) {
        websocketService.unsubscribe('connection_state', stateListenerRef.current);
      }
      websocketService.disconnect();
    };
  }, []);

  const value = {
    isConnected,
    connectionState,
    socket: websocketService.socket,
    sendMessage: (message) => websocketService.send(message),
    subscribe: (type, callback) => websocketService.subscribe(type, callback),
    unsubscribe: (type, callback) => websocketService.unsubscribe(type, callback)
  };

  return (
    <WebSocketContext.Provider value={value}>
      {children}
    </WebSocketContext.Provider>
  );
}
