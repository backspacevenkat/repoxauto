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
  Chip,
  LinearProgress,
  Checkbox,
  Tooltip,
  Divider
} from '@mui/material';
import { 
  Refresh as RefreshIcon,
  Key as KeyIcon,
  Download as DownloadIcon,
  Error as ErrorIcon,
  Upload as UploadIcon
} from '@mui/icons-material';
import axios from 'axios';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

export default function ActSetupPage() {
  const [accounts, setAccounts] = useState([]);
  const [totalAccounts, setTotalAccounts] = useState(0);
  const [file, setFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [threads, setThreads] = useState(6);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [importProgress, setImportProgress] = useState(null);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [processingAccounts, setProcessingAccounts] = useState({});
  const [completedOperations, setCompletedOperations] = useState({});
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(100);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('account_no');
  const [sortOrder, setSortOrder] = useState('asc');
  const { socket, isConnected } = useWebSocket();

  useEffect(() => {
    if (isConnected) {
      fetchAccounts();
    }
  }, [isConnected]);

  useEffect(() => {
    if (socket) {
      socket.addEventListener('message', handleWebSocketMessage);
      return () => socket.removeEventListener('message', handleWebSocketMessage);
    }
  }, [socket]);

  // Add debounced fetch for pagination/sorting/search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (isConnected) {
        setPage(0); // Reset to first page when search changes
        fetchAccounts();
      }
    }, 300); // Debounce time

    return () => clearTimeout(timer);
  }, [searchQuery]); // Only depend on searchQuery for this effect

  // Separate effect for pagination and sorting
  useEffect(() => {
    if (isConnected) {
      fetchAccounts();
    }
  }, [page, rowsPerPage, sortBy, sortOrder]);

  const handleWebSocketMessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      console.log("WebSocket message:", data); // Debug log
      
      switch (data.type) {
        case 'oauth_status':
          handleSetupStatusUpdate(data);
          break;
        case 'password_update':
          handlePasswordUpdateStatus(data);
          break;
        case 'import_status':
          handleImportStatus(data);
          break;
      }
    } catch (err) {
      console.error('Error handling WebSocket message:', err);
    }
  };

  const handleSetupStatusUpdate = (data) => {
    if (data.account_no) {
      console.log("OAuth status update:", data); // Debug log
      
      // Update accounts list for OAuth status changes
      setAccounts(prevAccounts => 
        prevAccounts.map(account => {
          if (account.account_no === data.account_no) {
            let oauth_status;
            switch (data.status) {
              case 'started':
                oauth_status = 'IN_PROGRESS';
                break;
              case 'completed':
                oauth_status = 'COMPLETED';
                break;
              case 'failed':
                oauth_status = 'FAILED';
                break;
              default:
                oauth_status = 'PENDING';
            }
            return {
              ...account,
              oauth_setup_status: oauth_status
            };
          }
          return account;
        })
      );

      // Update processing status
      if (data.status === 'started') {
        setProcessingAccounts(prev => ({
          ...prev,
          [data.account_no]: {
            type: 'oauth_status',
            status: data.status,
            message: data.message
          }
        }));
      }

      // Update completed operations
      if (data.status === 'completed') {
        setCompletedOperations(prev => ({
          ...prev,
          [data.account_no]: {
            ...prev[data.account_no],
            oauth: 'COMPLETED'
          }
        }));
        // Remove from processing after completion
        setProcessingAccounts(prev => {
          const newState = { ...prev };
          delete newState[data.account_no];
          return newState;
        });
      }

      // Handle failures
      if (data.status === 'failed') {
        setProcessingAccounts(prev => {
          const newState = { ...prev };
          delete newState[data.account_no];
          return newState;
        });
      }

      // Refresh account list after completion or failure
      if (data.status === 'completed' || data.status === 'failed') {
        fetchAccounts();
      }
    }
  };

  const handlePasswordUpdateStatus = (data) => {
    if (data.account_no) {
      console.log("Password update status:", data); // Debug log
      
      if (data.status === 'started') {
        setProcessingAccounts(prev => ({
          ...prev,
          [data.account_no]: {
            type: 'password_update',
            status: data.status,
            message: data.message
          }
        }));
      }

      if (data.status === 'completed') {
        // Update both completedOperations and accounts
        setCompletedOperations(prev => ({
          ...prev,
          [data.account_no]: {
            ...prev[data.account_no],
            password: 'COMPLETED'
          }
        }));
        
        setAccounts(prevAccounts => 
          prevAccounts.map(account => {
            if (account.account_no === data.account_no) {
              return {
                ...account,
                password_status: 'COMPLETED'
              };
            }
            return account;
          })
        );
        
        // Remove from processing after completion
        setProcessingAccounts(prev => {
          const newState = { ...prev };
          delete newState[data.account_no];
          return newState;
        });
      }

      if (data.status === 'error') {
        setProcessingAccounts(prev => {
          const newState = { ...prev };
          delete newState[data.account_no];
          return newState;
        });
        // Update accounts to show error
        setAccounts(prevAccounts => 
          prevAccounts.map(account => {
            if (account.account_no === data.account_no) {
              return {
                ...account,
                last_validation: data.message
              };
            }
            return account;
          })
        );
      }
    }
  };

  const handleImportStatus = (data) => {
    switch (data.status) {
      case 'started':
        setImportProgress({
          status: 'started',
          total: data.total,
          successful: 0,
          failed: 0,
          percent: 0
        });
        break;
      case 'processing':
        setImportProgress({
          status: 'processing',
          total: data.total,
          successful: data.successful,
          failed: data.failed,
          percent: Math.round((data.successful + data.failed) * 100 / data.total)
        });
        break;
      case 'completed':
        setImportProgress(null);
        setSuccessMessage(data.message);
        fetchAccounts();
        break;
      case 'error':
        setImportProgress(null);
        setError(data.message);
        break;
    }
  };

  async function fetchAccounts() {
    try {
        setLoading(true);
        console.log("Fetching accounts...");
        
        const params = new URLSearchParams({
            skip: page * rowsPerPage,
            limit: rowsPerPage,
            sort_by: sortBy,
            sort_order: sortOrder
        });
        
        if (searchQuery) {
            params.set('search', searchQuery);
        }

        const res = await axios.get(`${API_BASE_URL}/accounts?${params}`, {
            timeout: 30000,
            headers: {
                'Accept': 'application/json'
            }
        });
        
        if (!res.data || !Array.isArray(res.data.accounts)) {
            throw new Error('Invalid response format from server');
        }
        
        setAccounts(res.data.accounts);
        setTotalAccounts(res.data.total || 0);
        setError(null);
        
    } catch (err) {
        console.error("Error fetching accounts:", err);
        const errorMessage = err.response?.data?.detail || err.message;
        setError(`Error fetching accounts: ${errorMessage}`);
    } finally {
        setLoading(false);
    }
  }

  async function handleImport(e) {
    e.preventDefault();
    if (!file) {
      setError('Please select a CSV file');
      setTimeout(() => setError(null), 5000);
      return;
    }

    setLoading(true);
    const formData = new FormData();
    formData.append('file', file);

    let success = false;
    let retryCount = 0;
    const MAX_RETRIES = 3;
    const RETRY_DELAY = 5000;

    while (!success && retryCount < MAX_RETRIES) {
      try {
        await axios.post(`${API_BASE_URL}/accounts/setup/import`, formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          },
          timeout: 30000 // 30 second timeout
        });
        success = true;
      } catch (err) {
        const errorMessage = err.response?.data?.detail || err.message;
        console.error(`Import error (attempt ${retryCount + 1}):`, errorMessage);

        if (retryCount < MAX_RETRIES - 1 && 
            (errorMessage.includes("timeout") || 
             errorMessage.includes("connection") ||
             err.code === 'ECONNABORTED')) {
          retryCount++;
          setError(`Retrying file import (Attempt ${retryCount}/${MAX_RETRIES})`);
          await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
        } else {
          // If we've exhausted retries or it's not a retryable error
          setError(`Error importing file: ${errorMessage}`);
          setTimeout(() => setError(null), 5000);
          break;
        }
      }
    }

    setLoading(false);
    if (success) {
      setFile(null);
      setSuccessMessage('File import started successfully');
      setTimeout(() => setSuccessMessage(null), 3000);
    }
  }

  async function handleStartOAuth(accountNos = null, e) {
    // Prevent any event propagation
    if (e) e.preventDefault();

    // Ensure we always have an array of account numbers
    const accountsToProcess = Array.isArray(accountNos) 
        ? accountNos 
        : accountNos 
            ? [accountNos] 
            : selectedAccounts;
    
    if (accountsToProcess.length === 0) {
      setError('Please select accounts to set up OAuth');
      setTimeout(() => setError(null), 5000);
      return;
    }

    try {
      // Reset completed operations for accounts being updated
      setCompletedOperations(prev => {
        const newState = { ...prev };
        accountsToProcess.forEach(acc => {
          if (newState[acc]) {
            delete newState[acc].oauth;
          }
        });
        return newState;
      });

      // Send only the required data in a clean payload
      const payload = {
        accounts: accountsToProcess.map(acc => String(acc)), // Ensure account numbers are strings
        threads: Number(threads) // Ensure thread count is a number
      };

      const response = await axios.post(
        `${API_BASE_URL}/accounts/setup/oauth/bulk`,
        payload
      );

      if (response.data?.successful?.length) {
        setSuccessMessage(`Successfully started OAuth setup for ${response.data.successful.length} accounts`);
        setTimeout(() => setSuccessMessage(null), 3000);
      }

      // Check for any failed accounts in the response
      if (response.data?.failed?.length) {
        const failedMessage = response.data.failed.map(acc => 
          `Account ${acc}`
        ).join('\n');
        
        setError(
          `OAuth setup completed with errors:\n` +
          `Success: ${response.data.successful.length}\n` +
          `Failed: ${response.data.failed.length}\n\n` +
          `Failed accounts:\n${failedMessage}`
        );
      }
    } catch (err) {
      const errorMessage = err.response?.data?.detail || err.message;
      console.error('OAuth setup error:', errorMessage);
      setError(`Error in OAuth setup: ${errorMessage}`);
      setTimeout(() => setError(null), 5000);
    }
  }

  async function handleBulkPasswordUpdate(accountNos = null, e) {
    // Prevent any event propagation
    if (e) e.preventDefault();

    // Ensure we always have an array of account numbers
    const accountsToUpdate = Array.isArray(accountNos) 
        ? accountNos 
        : accountNos 
            ? [accountNos] 
            : selectedAccounts;
    
    if (accountsToUpdate.length === 0) {
      setError('Please select accounts to update passwords');
      setTimeout(() => setError(null), 5000);
      return;
    }

    const failedAccounts = [];
    let successCount = 0;
    let skippedAccounts = [];

    try {
        // Filter out accounts that already have long passwords
        const accountsNeedingUpdate = accountsToUpdate.filter(accNo => {
          const account = accounts.find(a => a.account_no === accNo);
          if (account?.password_status === 'COMPLETED') {
            skippedAccounts.push(accNo);
            // Mark as completed since password is already long enough
            setCompletedOperations(prev => ({
              ...prev,
              [accNo]: {
                ...prev[accNo],
                password: 'COMPLETED'
              }
            }));
            return false;
          }
          return true;
        });

        if (accountsNeedingUpdate.length === 0) {
          setSuccessMessage(`All selected accounts already have strong passwords`);
          setTimeout(() => setSuccessMessage(null), 3000);
          return;
        }

        // Reset completed operations for accounts being updated
        setCompletedOperations(prev => {
          const newState = { ...prev };
          accountsNeedingUpdate.forEach(acc => {
            if (newState[acc] && !skippedAccounts.includes(acc)) {
              delete newState[acc].password;
            }
          });
          return newState;
        });

        // Send accounts that need update in a single request with thread count
        const response = await axios.post(
            `${API_BASE_URL}/accounts/setup/password/update/bulk`,
            { 
              accounts: accountsNeedingUpdate.map(acc => String(acc)), // Ensure account numbers are strings
              threads: Number(threads) // Ensure thread count is a number
            }
        );

        if (response.data?.successful?.length) {
            successCount = response.data.successful.length;
        }

        // Check for any failed accounts in the response
        if (response.data?.failed?.length) {
            failedAccounts.push(...response.data.failed.map(acc => ({
                accountNo: acc,
                error: 'Failed to update password'
            })));
        }
    } catch (err) {
        const errorMessage = err.response?.data?.detail || err.message;
        console.error('Password update error:', errorMessage);
        
        // Ensure we're pushing objects for each failed account
        failedAccounts.push(...accountsToUpdate.map(acc => ({
            accountNo: acc,
            error: errorMessage
        })));
    }

    // Show final status
    if (failedAccounts.length > 0) {
        const failedMessage = failedAccounts.map(f => 
            `Account ${f.accountNo}: ${f.error}`
        ).join('\n');
        
        setError(
            `Password update completed with errors:\n` +
            `Success: ${successCount}\n` +
            `Failed: ${failedAccounts.length}\n\n` +
            `Failed accounts:\n${failedMessage}`
        );
    } else {
        setSuccessMessage(`Successfully started password update for ${successCount} accounts`);
        setTimeout(() => setSuccessMessage(null), 3000);
    }
}

  async function handleDownloadSelected() {
    if (selectedAccounts.length === 0) {
      setError('Please select accounts to download');
      setTimeout(() => setError(null), 5000);
      return;
    }

    let success = false;
    let retryCount = 0;
    const MAX_RETRIES = 3;
    const RETRY_DELAY = 5000;

    while (!success && retryCount < MAX_RETRIES) {
      try {
        const response = await axios.post(
          `${API_BASE_URL}/accounts/setup/download`,
          { accounts: selectedAccounts },
          { 
            responseType: 'blob',
            timeout: 30000 // 30 second timeout
          }
        );

        // Verify the response is valid CSV data
        const contentType = response.headers['content-type'];
        if (!contentType || !contentType.includes('text/csv')) {
          throw new Error('Invalid response format - expected CSV');
        }

        const url = window.URL.createObjectURL(new Blob([response.data], { type: 'text/csv' }));
        const link = document.createElement('a');
        link.href = url;
        const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
        link.setAttribute('download', `accounts_export_${timestamp}.csv`);
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
        
        success = true;
        setSuccessMessage(`Successfully downloaded ${selectedAccounts.length} accounts`);
        setTimeout(() => setSuccessMessage(null), 3000);

      } catch (err) {
        const errorMessage = err.response?.data?.detail || err.message;
        console.error(`Download error (attempt ${retryCount + 1}):`, errorMessage);

        if (retryCount < MAX_RETRIES - 1 && 
            (errorMessage.includes("timeout") || 
             errorMessage.includes("connection") ||
             err.code === 'ECONNABORTED')) {
          retryCount++;
          setError(`Retrying download (Attempt ${retryCount}/${MAX_RETRIES})`);
          await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
        } else {
          setError(`Error downloading accounts: ${errorMessage}`);
          setTimeout(() => setError(null), 5000);
          break;
        }
      }
    }
  }

  function getStatusColor(status) {
    if (!status) return 'default';
    const lower = status.toLowerCase();
    if (lower.includes('success') || lower.includes('completed')) return 'success';
    if (lower.includes('error') || lower.includes('failed')) return 'error';
    if (lower.includes('progress')) return 'info';
    return 'warning';
  }

  // Get all account numbers for bulk selection
  const getAllAccountNumbers = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/accounts/all-account-numbers`);
      return response.data.account_numbers || [];
    } catch (err) {
      console.error('Error fetching all account numbers:', err);
      return [];
    }
  };

  // Use server-side pagination, so just return all accounts
  const getCurrentPageAccounts = () => {
    return accounts;
  };

  async function handleDelete(accountNo) {
    try {
      // Show confirmation dialog
      if (!window.confirm(`Are you sure you want to delete account ${accountNo}?`)) {
        return;
      }

      const response = await axios.delete(`${API_BASE_URL}/accounts/${accountNo}`);
      
      if (response.data?.status === 'success') {
        setSuccessMessage(response.data.message);
        // Remove from selected accounts if it was selected
        setSelectedAccounts(prev => prev.filter(no => no !== accountNo));
        // Refresh the accounts list
        fetchAccounts();
      }
    } catch (err) {
      const errorMessage = err.response?.data?.detail || err.message;
      setError(`Error deleting account: ${errorMessage}`);
      setTimeout(() => setError(null), 5000);
    }
  }

  return (
    <Container maxWidth="xl" sx={{ mb: 3 }}>
      <Typography variant="h5" gutterBottom sx={{ mb: 3 }}>Account Setup</Typography>

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

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" gutterBottom>Import Accounts</Typography>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mb: 2 }}>
          <form onSubmit={handleImport} style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <Button
              variant="contained"
              component="label"
              disabled={loading}
              startIcon={<UploadIcon />}
            >
              Select CSV File
              <input
                type="file"
                onChange={e => setFile(e.target.files[0])}
                accept=".csv"
                style={{ display: 'none' }}
              />
            </Button>
            <Typography>
              {file ? file.name : 'No file selected'}
            </Typography>
            <Button
              type="submit"
              variant="contained"
              color="primary"
              disabled={loading || !file}
            >
              {loading ? 'Importing...' : 'Import Accounts'}
            </Button>
          </form>
        </Box>

        {importProgress && (
          <Box sx={{ width: '100%', mt: 2 }}>
            <Typography variant="body2" color="textSecondary" gutterBottom>
              Importing accounts... ({importProgress.percent}%)
            </Typography>
            <LinearProgress 
              variant="determinate" 
              value={importProgress.percent}
              sx={{ height: 8, borderRadius: 1 }}
            />
          </Box>
        )}
      </Paper>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="h6">Account Actions</Typography>
          <TextField
            size="small"
            placeholder="Search accounts..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(0); // Reset to first page when searching
            }}
            sx={{ width: 250 }}
          />
        </Box>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mb: 2 }}>
          <TextField
            label="Threads"
            type="number"
            size="small"
            value={threads}
            onChange={e => {
              const value = parseInt(e.target.value, 10);
              if (value >= 1 && value <= 12) {
                setThreads(value);
              } else {
                setThreads(6); // Reset to default if invalid
                setError('Thread count must be between 1 and 12');
                setTimeout(() => setError(null), 3000);
              }
            }}
            InputProps={{ inputProps: { min: 1, max: 12 } }}
            sx={{ width: 100 }}
          />
          <Button
            variant="contained"
            color="primary"
            onClick={(e) => handleStartOAuth(null, e)}
            disabled={selectedAccounts.length === 0}
            startIcon={<RefreshIcon />}
          >
            Start OAuth Setup
          </Button>
          <Button
            variant="contained"
            color="primary"
            onClick={(e) => handleBulkPasswordUpdate(selectedAccounts, e)}
            disabled={selectedAccounts.length === 0}
            startIcon={<KeyIcon />}
          >
            Generate New Passwords
          </Button>
          <Button
            variant="contained"
            onClick={handleDownloadSelected}
            disabled={selectedAccounts.length === 0}
            startIcon={<DownloadIcon />}
          >
            Download Selected
          </Button>
        </Box>

      </Paper>

      <TableContainer component={Paper} sx={{ minHeight: 400, borderRadius: 2, position: 'relative' }}>
        {loading && (
          <Box 
            sx={{ 
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: 'rgba(255, 255, 255, 0.7)',
              zIndex: 1
            }}
          >
            <CircularProgress />
          </Box>
        )}
        <Table stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell padding="checkbox">
                <Checkbox
                  onChange={async (e) => {
                    if (e.target.checked) {
                      // Get all account numbers and select them
                      const allAccountNumbers = await getAllAccountNumbers();
                      setSelectedAccounts(allAccountNumbers);
                    } else {
                      // Clear all selections
                      setSelectedAccounts([]);
                    }
                  }}
                  checked={selectedAccounts.length > 0 && selectedAccounts.length >= totalAccounts}
                  indeterminate={selectedAccounts.length > 0 && selectedAccounts.length < totalAccounts}
                />
              </TableCell>
              {[
                { id: 'account_no', label: 'Account No' },
                { id: 'login', label: 'Login' },
                { id: 'oauth_setup_status', label: 'OAuth Status' },
                { id: 'password_status', label: 'Password Status' },
                { id: 'last_validation', label: 'Last Error' },
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
            {getCurrentPageAccounts().map(account => (
              <TableRow key={account.account_no}>
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={selectedAccounts.includes(account.account_no)}
                    onChange={e => {
                      if (e.target.checked) {
                        // Add this account to existing selections
                        setSelectedAccounts(prev => [...prev, account.account_no]);
                      } else {
                        // Remove this account while keeping others
                        setSelectedAccounts(prev => prev.filter(no => no !== account.account_no));
                      }
                    }}
                  />
                </TableCell>
                <TableCell>{account.account_no}</TableCell>
                <TableCell>{account.login}</TableCell>
                <TableCell>
                  {/* OAuth Status */}
                  {processingAccounts[account.account_no]?.type === 'oauth_status' ? (
                    <Chip
                      label={processingAccounts[account.account_no].status === 'started' ? 'IN PROGRESS' : processingAccounts[account.account_no].status}
                      color={getStatusColor(processingAccounts[account.account_no].status)}
                      size="small"
                    />
                  ) : (
                    <Chip
                      label={account.oauth_setup_status}
                      color={account.oauth_setup_status === 'ACTIVE' || account.oauth_setup_status === 'COMPLETED' ? 'success' : 'warning'}
                      size="small"
                    />
                  )}
                </TableCell>
                <TableCell>
                  {/* Password Status */}
                  {processingAccounts[account.account_no]?.type === 'password_update' ? (
                    <Chip
                      label={processingAccounts[account.account_no].status}
                      color={getStatusColor(processingAccounts[account.account_no].status)}
                      size="small"
                    />
                  ) : completedOperations[account.account_no]?.password === 'COMPLETED' || 
                      account.password_status === 'COMPLETED' ? (
                    <Chip
                      label="COMPLETED"
                      color="success"
                      size="small"
                    />
                  ) : (
                    <Chip
                      label="Not Updated"
                      color="default"
                      size="small"
                    />
                  )}
                </TableCell>
                <TableCell>
                  {/* Only show errors from OAuth or password operations */}
                  {account.last_validation && 
                   (account.last_validation.includes('oauth') || 
                    account.last_validation.includes('password') || 
                    account.last_validation.includes('credentials')) && 
                   !account.last_validation.includes('successfully') && (
                    <Tooltip title={account.last_validation}>
                      <ErrorIcon color="error" fontSize="small" />
                    </Tooltip>
                  )}
                </TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                      size="small"
                      variant="contained"
                      onClick={(e) => handleStartOAuth([account.account_no], e)}
                      startIcon={<RefreshIcon />}
                    >
                      Start OAuth
                    </Button>
                    <Button
                      size="small"
                      variant="contained"
                      onClick={(e) => handleBulkPasswordUpdate([account.account_no], e)}
                      startIcon={<KeyIcon />}
                    >
                      Generate Password
                    </Button>
                  </Box>
                </TableCell>
              </TableRow>
            ))}
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
              (showing {rowsPerPage === Infinity ? totalAccounts : Math.min(rowsPerPage, accounts.length)} of {totalAccounts} accounts)
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
              setPage(0); // Reset to first page when changing rows per page
            }}
            style={{ 
              padding: '4px', 
              borderRadius: '4px',
              border: '1px solid #ccc',
              backgroundColor: 'white'
            }}
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <Typography variant="body2" color="text.secondary">
            Page {page + 1} of {Math.max(1, Math.ceil(totalAccounts / rowsPerPage))}
          </Typography>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              size="small"
              variant="outlined"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              Previous
            </Button>
            <Button
              size="small"
              variant="outlined"
              onClick={() => setPage(p => p + 1)}
              disabled={page >= Math.ceil(totalAccounts / rowsPerPage) - 1 || accounts.length === 0}
            >
              Next
            </Button>
          </Box>
        </Box>
      </Box>
    </Container>
  );
}
