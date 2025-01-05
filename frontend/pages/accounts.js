import React, { useEffect, useState } from 'react';
import { useWebSocket } from '../components/WebSocketProvider';
import {
  Box,
  Button,
  Container,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  TextField,
  Alert,
  CircularProgress,
  Link,
  Chip,
  LinearProgress
} from '@mui/material';
import { Refresh as RefreshIcon, Delete as DeleteIcon } from '@mui/icons-material';
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

// Helper function to get Twitter profile URL
const getTwitterUrl = (login) => {
  if (!login) return null;
  const username = login.startsWith('@') ? login.slice(1) : login;
  return `https://twitter.com/${username}`;
};

export default function AccountsPage() {
  const [accounts, setAccounts] = useState([]);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState({});
  const [recovering, setRecovering] = useState({});
  const [bulkValidating, setBulkValidating] = useState(false);
  const [bulkRecovering, setBulkRecovering] = useState(false);
  const [threads, setThreads] = useState(6);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [importProgress, setImportProgress] = useState(null);
  const [bulkProgress, setBulkProgress] = useState(null);
  const [refreshInterval, setRefreshInterval] = useState(null);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [sortBy, setSortBy] = useState('account_no');
  const [sortOrder, setSortOrder] = useState('asc');

  const { socket, isConnected } = useWebSocket();

  // Handle WebSocket connection status and polling
  useEffect(() => {
    let pollInterval = null;
    let reconnectTimeout = null;

    const startPolling = () => {
      if (!pollInterval) {
        fetchAccounts(); // Fetch immediately when starting polling
        pollInterval = setInterval(fetchAccounts, 5000);
      }
    };

    const stopPolling = () => {
      if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    };

    if (!isConnected) {
      setError('WebSocket disconnected. Real-time updates may be delayed.');
      startPolling();

      // Try to reconnect after a delay
      if (!reconnectTimeout) {
        reconnectTimeout = setTimeout(() => {
          if (!isConnected && socket) {
            socket.close(); // Close existing connection
            socket.addEventListener('close', () => {
              // Try to reconnect after socket is properly closed
              const wsUrl = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:9000/ws';
              const newSocket = new WebSocket(wsUrl);
              newSocket.addEventListener('open', () => {
                console.log('WebSocket reconnected');
                setError(null);
                fetchAccounts(); // Refresh data after reconnection
              });
            });
          }
        }, 5000); // Wait 5 seconds before trying to reconnect
      }
    } else {
      setError(null);
      stopPolling();
      
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
      }

      // Fetch accounts when connection is established
      fetchAccounts();
    }
    
    // Cleanup
    return () => {
      stopPolling();
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
      }
    };
  }, [isConnected, socket]);

  // Handle WebSocket messages
  useEffect(() => {
    if (!socket) return;

    const handleMessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('WebSocket message received:', data);
        
        switch (data.type) {
          case 'task_update':
            // Update single account status
            setAccounts(prevAccounts => 
              prevAccounts.map(acc => {
                if (acc.account_no === data.account_no) {
                  return {
                    ...acc,
                    validation_in_progress: data.status,
                    last_validation: data.validation_result,
                    last_validation_time: data.timestamp
                  };
                }
                return acc;
              })
            );

            // Show task message
            if (data.message) {
              if (data.status === 'failed') {
                setError(data.message);
                setTimeout(() => setError(null), 5000);
              } else {
                setSuccessMessage(data.message);
                setTimeout(() => setSuccessMessage(null), 3000);
              }
            }
            break;

          case 'bulk_validation':
            switch (data.status) {
              case 'started':
                setBulkProgress({
                  status: 'started',
                  total: data.total,
                  completed: 0,
                  failed: 0,
                  percent: 0,
                  message: data.message
                });
                break;
              case 'processing':
                setBulkProgress({
                  status: 'processing',
                  total: data.total,
                  completed: data.completed,
                  failed: data.failed,
                  percent: Math.round((data.completed + data.failed) * 100 / data.total),
                  message: data.message
                });
                break;
              case 'completed':
                setBulkProgress(null);
                setBulkValidating(false);
                setBulkRecovering(false);
                setSuccessMessage(data.message);
                setTimeout(() => setSuccessMessage(null), 5000);
                break;
              case 'error':
                setBulkProgress(null);
                setBulkValidating(false);
                setBulkRecovering(false);
                setError(data.message);
                setTimeout(() => setError(null), 5000);
                break;
            }
            break;

          case 'import_status':
            switch (data.status) {
              case 'started':
                setImportProgress({
                  status: 'started',
                  total: 0,
                  successful: 0,
                  failed: 0,
                  percent: 0,
                  message: data.message
                });
                break;
              case 'processing':
                setImportProgress({
                  status: 'processing',
                  total: data.total,
                  successful: data.successful,
                  failed: data.failed,
                  percent: data.total ? Math.round((data.successful + data.failed) * 100 / data.total) : 0,
                  message: data.message
                });
                break;
              case 'completed':
                setImportProgress(null);
                setSuccessMessage(data.message);
                fetchAccounts(); // Refresh the accounts list
                setTimeout(() => setSuccessMessage(null), 5000);
                break;
              case 'error':
                setImportProgress(null);
                setError(data.message);
                setTimeout(() => setError(null), 5000);
                break;
            }
            break;
        }
      } catch (err) {
        console.error('Error handling WebSocket message:', err);
      }
    };

    socket.addEventListener('message', handleMessage);
    return () => socket.removeEventListener('message', handleMessage);
  }, [socket]);

  async function fetchAccounts() {
    try {
      const res = await axios.get(`${API_BASE_URL}/accounts`);
      setAccounts(Array.isArray(res.data) ? res.data : []);
      
      if (bulkValidating || bulkRecovering) {
        const allComplete = res.data.every(acc => 
          acc.validation_in_progress !== 'in_progress' && 
          acc.validation_in_progress !== 'validating' &&
          acc.validation_in_progress !== 'recovering' &&
          acc.last_validation_time !== null
        );
        
        const anyValidated = res.data.some(acc => 
          acc.last_validation_time !== null &&
          new Date(acc.last_validation_time) > new Date(Date.now() - 60000)
        );
        
        if (allComplete && anyValidated) {
          setBulkValidating(false);
          setBulkRecovering(false);
          setSuccessMessage('Bulk operation completed');
          setTimeout(() => setSuccessMessage(null), 5000);
        }
      }
    } catch (err) {
      setError('Error fetching accounts: ' + err.message);
      setTimeout(() => setError(null), 5000);
      setAccounts([]);
    }
  }

  async function handleUpload(e) {
    e.preventDefault();
    if (!file) {
      setError('Please select a CSV file');
      setTimeout(() => setError(null), 5000);
      return;
    }

    // Check file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError('File too large (max 10MB)');
      setTimeout(() => setError(null), 5000);
      return;
    }

    // Check file type
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setError('Please upload a CSV file');
      setTimeout(() => setError(null), 5000);
      return;
    }
    
    setLoading(true);
    setImportProgress({ status: 'started', message: 'Starting upload...' });
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000); // 60 second timeout
      
      const response = await axios.post(`${API_BASE_URL}/accounts/import`, formData, {
        signal: controller.signal,
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
            setImportProgress({
              status: 'uploading',
              percent: percentCompleted,
              message: `Uploading: ${percentCompleted}%`
            });
          }
        }
      });

      clearTimeout(timeoutId);
      
    } catch (err) {
      let errorMsg = 'Error importing accounts';
      if (err.name === 'AbortError') {
        errorMsg = 'Upload timed out. Please try again.';
      } else if (err.response?.data?.detail) {
        errorMsg += ': ' + err.response.data.detail;
      } else if (err.message) {
        errorMsg += ': ' + err.message;
      }
      setError(errorMsg);
      setImportProgress(null);
      setTimeout(() => setError(null), 5000);
    } finally {
      setLoading(false);
      setFile(null); // Reset file input
    }
  }

  async function handleValidate(account_no) {
    setValidating(prev => ({...prev, [account_no]: true}));
    try {
      const res = await axios.post(`${API_BASE_URL}/accounts/validate/${account_no}`);
      setSuccessMessage(`Validation result for ${account_no}: ${res.data.validation_result}`);
      setTimeout(() => setSuccessMessage(null), 5000);
      
      if (res.data.validation_result.toLowerCase().includes('suspended') || 
          res.data.validation_result.toLowerCase().includes('locked') ||
          res.data.validation_result.toLowerCase().includes('unavailable')) {
        await handleRecover(account_no);
      }
    } catch (err) {
      setError(`Error validating account ${account_no}: ${err.message}`);
      setTimeout(() => setError(null), 5000);
    }
    setValidating(prev => ({...prev, [account_no]: false}));
  }

  async function handleRecover(account_no) {
    setRecovering(prev => ({...prev, [account_no]: true}));
    try {
      const res = await axios.post(`${API_BASE_URL}/accounts/recover/${account_no}`);
      setSuccessMessage(`Recovery result for ${account_no}: ${res.data.recovery_result}`);
      setTimeout(() => setSuccessMessage(null), 5000);
    } catch (err) {
      setError(`Error recovering account ${account_no}: ${err.message}`);
      setTimeout(() => setError(null), 5000);
    }
    setRecovering(prev => ({...prev, [account_no]: false}));
  }

  async function handleDelete(account_no) {
    if (!confirm(`Are you sure you want to delete account ${account_no}?`)) {
      return;
    }

    try {
      await axios.delete(`${API_BASE_URL}/accounts/${account_no}`);
      setSuccessMessage(`Account ${account_no} deleted`);
      setTimeout(() => setSuccessMessage(null), 5000);
      await fetchAccounts();
    } catch (err) {
      setError(`Error deleting account ${account_no}: ${err.message}`);
      setTimeout(() => setError(null), 5000);
    }
  }

  async function handleBulkValidate() {
    if (bulkValidating) return;
    
    const numThreads = parseInt(threads, 10);
    if (isNaN(numThreads) || numThreads < 1 || numThreads > 12) {
      setError('Invalid number of threads (must be between 1 and 12)');
      setTimeout(() => setError(null), 5000);
      return;
    }
    
    setBulkValidating(true);
    try {
      // Update UI immediately
      setAccounts(prev => prev.map(acc => ({
        ...acc,
        validation_in_progress: 'validating'
      })));
      
      // Start validation
      await axios.post(`${API_BASE_URL}/accounts/validate-all`, null, {
        params: { threads: numThreads }
      });
      
      setSuccessMessage('Bulk validation started');
      setTimeout(() => setSuccessMessage(null), 5000);
      
    } catch (err) {
      // Revert UI state on error
      setAccounts(prev => prev.map(acc => ({
        ...acc,
        validation_in_progress: acc.validation_in_progress === 'validating' ? null : acc.validation_in_progress
      })));
      setBulkValidating(false);
      setError('Error starting bulk validation: ' + err.message);
      setTimeout(() => setError(null), 5000);
    }
  }

  function getStatusColor(status) {
    if (!status) return 'default';
    const lower = status.toLowerCase();
    if (lower.includes('active') || lower.includes('recovered')) return 'success';
    if (lower.includes('error') || lower.includes('failed')) return 'error';
    if (lower.includes('progress') || lower.includes('validating') || lower.includes('recovering')) return 'info';
    return 'warning';
  }

  function formatDate(dateStr) {
    if (!dateStr) return 'Never';
    return new Date(dateStr).toLocaleString('en-US', {
      timeZone: 'America/Los_Angeles',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hour12: true,
      timeZoneName: 'short'
    });
  }

  return (
    <Container maxWidth="xl" sx={{ mb: 3 }}>
      <Typography variant="h5" gutterBottom sx={{ mb: 3 }}>Account Management</Typography>
      
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      
      {successMessage && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {successMessage}
        </Alert>
      )}

      <Paper sx={{ p: 2, mb: 3, backgroundColor: 'background.paper', borderRadius: 2 }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
          <form onSubmit={handleUpload} style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <Button
                variant="contained"
                component="label"
                disabled={loading}
              >
                Select CSV File
                <input
                  type="file"
                  key={file ? 'has-file' : 'no-file'} // Reset input when file is cleared
                  onChange={e => setFile(e.target.files[0])}
                  accept=".csv"
                  style={{ display: 'none' }}
                />
              </Button>
              <Typography sx={{ minWidth: '200px' }}>
                {file ? file.name : 'No file selected'}
              </Typography>
              <Box sx={{ position: 'relative' }}>
                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  disabled={loading || !file}
                >
                  {loading ? 'Importing...' : 'Import CSV'}
                </Button>
                {loading && (
                  <CircularProgress
                    size={24}
                    sx={{
                      position: 'absolute',
                      top: '50%',
                      left: '50%',
                      marginTop: '-12px',
                      marginLeft: '-12px',
                    }}
                  />
                )}
              </Box>
            </Box>
          </form>

          <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', ml: 'auto' }}>
            <TextField
              label="Parallel Threads"
              type="number"
              size="small"
              value={threads}
              onChange={e => setThreads(parseInt(e.target.value, 10))}
              InputProps={{ 
                inputProps: { min: 1, max: 12 }
              }}
              sx={{ width: 120 }}
            />
            <Button
              variant="contained"
              color="primary"
              onClick={handleBulkValidate}
              disabled={bulkValidating || bulkRecovering}
              startIcon={bulkValidating ? <CircularProgress size={20} /> : <RefreshIcon />}
            >
              {bulkValidating ? 'Validating...' : 'Validate All'}
            </Button>
          </Box>
        </Box>

        {(importProgress || bulkProgress) && (
          <Box sx={{ width: '100%', mt: 2, transition: 'all 0.3s ease-in-out' }}>
            {importProgress && (
              <>
                <Typography variant="body2" color="textSecondary" gutterBottom>
                  {importProgress.message || (
                    importProgress.status === 'processing' 
                      ? `Processing: ${importProgress.successful} successful, ${importProgress.failed} failed out of ${importProgress.total}`
                      : 'Processing...'
                  )}
                </Typography>
                <LinearProgress 
                  variant="determinate" 
                  value={importProgress.percent || 0}
                  sx={{ 
                    height: 8, 
                    borderRadius: 1, 
                    mb: 2,
                    '& .MuiLinearProgress-bar': {
                      transition: 'transform 0.3s ease-in-out'
                    }
                  }}
                />
              </>
            )}
            {bulkProgress && (
              <>
                <Typography variant="body2" color="textSecondary" gutterBottom>
                  {bulkProgress.message || (
                    bulkProgress.status === 'processing'
                      ? `Validating: ${bulkProgress.completed} completed, ${bulkProgress.failed} failed out of ${bulkProgress.total}`
                      : 'Processing...'
                  )}
                </Typography>
                <LinearProgress 
                  variant="determinate" 
                  value={bulkProgress.percent || 0}
                  sx={{ 
                    height: 8, 
                    borderRadius: 1,
                    '& .MuiLinearProgress-bar': {
                      transition: 'transform 0.3s ease-in-out'
                    }
                  }}
                />
              </>
            )}
          </Box>
        )}
      </Paper>

      <TableContainer component={Paper} sx={{ minHeight: 400, borderRadius: 2 }}>
        <Table stickyHeader aria-label="accounts table">
          <TableHead>
            <TableRow>
              {[
                { id: 'account_no', label: 'Account No' },
                { id: 'act_type', label: 'Type' },
                { id: 'login', label: 'Login' },
                { id: 'validation_in_progress', label: 'Status' },
                { id: 'last_validation', label: 'Last Validation' },
                { id: 'last_validation_time', label: 'Last Validation Time' },
                { id: 'actions', label: 'Actions', sortable: false }
              ].map((column) => (
                <TableCell
                  key={column.id}
                  sortDirection={sortBy === column.id ? sortOrder : false}
                  sx={column.sortable !== false ? {
                    cursor: 'pointer',
                    '&:hover': {
                      backgroundColor: 'action.hover'
                    }
                  } : {}}
                  onClick={() => {
                    if (column.sortable !== false) {
                      const isAsc = sortBy === column.id && sortOrder === 'asc';
                      setSortOrder(isAsc ? 'desc' : 'asc');
                      setSortBy(column.id);
                    }
                  }}
                >
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    {column.label}
                    {column.sortable !== false && sortBy === column.id && (
                      <span style={{ fontSize: '0.8em' }}>
                        {sortOrder === 'asc' ? '↑' : '↓'}
                      </span>
                    )}
                  </Box>
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {accounts.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center" sx={{ py: 8 }}>
                  <Typography variant="body1" color="text.secondary" gutterBottom>
                    No accounts found
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Import accounts using the CSV upload button above
                  </Typography>
                </TableCell>
              </TableRow>
            ) : (
              [...accounts]
                .sort((a, b) => {
                  const aValue = a[sortBy];
                  const bValue = b[sortBy];
                  
                  if (!aValue && !bValue) return 0;
                  if (!aValue) return 1;
                  if (!bValue) return -1;
                  
                  const comparison = aValue.toString().localeCompare(bValue.toString());
                  return sortOrder === 'asc' ? comparison : -comparison;
                })
                .slice(page * rowsPerPage, (page + 1) * rowsPerPage)
                .map(acc => (
                  <TableRow key={acc.id}>
                    <TableCell>{acc.account_no}</TableCell>
                    <TableCell>{acc.act_type}</TableCell>
                    <TableCell>
                      {acc.login && (
                        <Link
                          href={getTwitterUrl(acc.login)}
                          target="_blank"
                          rel="noopener noreferrer"
                          sx={{ 
                            display: 'flex',
                            alignItems: 'center',
                            gap: 0.5,
                            color: 'primary.main',
                            fontWeight: 'medium',
                            '&:hover': {
                              textDecoration: 'underline',
                              color: 'primary.dark'
                            }
                          }}
                        >
                          @{acc.login}
                          <span style={{ fontSize: '0.8em', marginLeft: '2px' }}>↗️</span>
                        </Link>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={acc.validation_in_progress || 'Not Started'}
                        color={getStatusColor(acc.validation_in_progress)}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={acc.last_validation || 'Never'}
                        color={getStatusColor(acc.last_validation)}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{formatDate(acc.last_validation_time)}</TableCell>
                    <TableCell>
                      <Box sx={{ display: 'flex', gap: 1 }}>
                        <Button
                          size="small"
                          variant="contained"
                          onClick={() => handleValidate(acc.account_no)}
                          disabled={validating[acc.account_no] || recovering[acc.account_no] || bulkValidating || bulkRecovering}
                          startIcon={validating[acc.account_no] ? <CircularProgress size={16} /> : <RefreshIcon />}
                        >
                          {validating[acc.account_no] ? 'Validating...' : 'Validate'}
                        </Button>
                        <Button
                          size="small"
                          variant="contained"
                          color="error"
                          onClick={() => handleDelete(acc.account_no)}
                          startIcon={<DeleteIcon />}
                        >
                          Delete
                        </Button>
                      </Box>
                    </TableCell>
                  </TableRow>
                ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <Box sx={{ 
        display: 'flex', 
        justifyContent: 'space-between', 
        alignItems: 'center', 
        mt: 2, 
        gap: 2,
        flexWrap: 'wrap'
      }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Typography variant="body2" color="text.secondary">
            {accounts.length === 0 ? 'No accounts' : 
             accounts.length === 1 ? '1 account' :
             `${accounts.length} accounts`}
          </Typography>
          {accounts.length > 0 && (
            <Typography variant="body2" color="text.secondary">
              (showing {Math.min(rowsPerPage, accounts.length)} per page)
            </Typography>
          )}
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Rows per page:
          </Typography>
          <select
            value={rowsPerPage}
            onChange={(e) => {
              setRowsPerPage(Number(e.target.value));
              setPage(0);
            }}
            style={{ 
              padding: '4px', 
              borderRadius: '4px',
              border: '1px solid #ccc',
              backgroundColor: 'white'
            }}
            disabled={accounts.length === 0}
          >
            {[5, 10, 25, 50].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <Typography variant="body2" color="text.secondary">
            Page {page + 1} of {Math.ceil(accounts.length / rowsPerPage)}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              size="small"
              variant="outlined"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0 || accounts.length === 0}
            >
              Previous
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={() => setPage(p => Math.min(Math.ceil(accounts.length / rowsPerPage) - 1, p + 1))}
              disabled={page >= Math.ceil(accounts.length / rowsPerPage) - 1 || accounts.length === 0}
            >
              Next
            </Button>
          </Box>
        </Box>
      </Box>
    </Container>
  );
}
