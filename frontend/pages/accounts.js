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
  LinearProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  IconButton,
  Tooltip,
  Checkbox,
  Collapse
} from '@mui/material';
import HelpTooltip from '../components/help/HelpTooltip';
import InfoCard from '../components/help/InfoCard';
import { 
  Refresh as RefreshIcon, 
  Delete as DeleteIcon, 
  Cookie as CookieIcon,
  ContentCopy as CopyIcon,
  Check as CheckIcon,
  Download as DownloadIcon
} from '@mui/icons-material';
import axios from 'axios';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

// Helper function to get Twitter profile URL
const getTwitterUrl = (login) => {
  if (!login) return null;
  const username = login.startsWith('@') ? login.slice(1) : login;
  return `https://twitter.com/${username}`;
};

export default function AccountsPage() {
  const { connectionState, isConnected, socket, sendMessage } = useWebSocket();
  const [accounts, setAccounts] = useState([]);
  const [totalAccounts, setTotalAccounts] = useState(0);
  const [selectedAccounts, setSelectedAccounts] = useState([]);
  const [file, setFile] = useState(null);
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(100);
  const [loading, setLoading] = useState(true);
  const [validating, setValidating] = useState({});
  const [recovering, setRecovering] = useState({});
  const [refreshing, setRefreshing] = useState({});
  const [bulkValidating, setBulkValidating] = useState(false);
  const [bulkRecovering, setBulkRecovering] = useState(false);
  const [threads, setThreads] = useState(6);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [importProgress, setImportProgress] = useState(null);
  const [bulkProgress, setBulkProgress] = useState(null);
  const [refreshInterval, setRefreshInterval] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState('account_no');
  const [sortOrder, setSortOrder] = useState('asc');
  const [cookieDialog, setCookieDialog] = useState({ open: false, ct0: '', auth_token: '' });
  const [copiedState, setCopiedState] = useState({ ct0: false, auth_token: false });

  const fetchAccounts = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams({
        skip: page * rowsPerPage,
        limit: rowsPerPage,
        sort_by: sortBy,
        sort_order: sortOrder
      });

      if (searchQuery) {
        params.set('search', searchQuery);
      }

      const response = await fetch(
        `${API_BASE_URL}/accounts?${params}`,
        {
          headers: {
            'Accept': 'application/json'
          }
        }
      );
      
      if (!response.ok) {
        throw new Error('Failed to fetch accounts');
      }
      
      const data = await response.json();
      setAccounts(data.accounts);
      setTotalAccounts(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

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

  // Update displayed accounts when accounts array changes
  useEffect(() => {
    // Don't clear selections when accounts update
    // setSelectedAccounts([]); // Remove this
  }, [accounts]);

  // Subscribe to WebSocket updates
  useEffect(() => {
    if (!socket) return;

    const handleMessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'account_update' || data.type === 'task_update' || data.type === 'oauth_status') {
          // Refresh accounts list when we receive updates
          fetchAccounts();
        }
      } catch (err) {
        console.error('Error processing message:', err);
      }
    };

    socket.addEventListener('message', handleMessage);

    return () => {
      socket.removeEventListener('message', handleMessage);
    };
  }, [socket, fetchAccounts]);

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

  // Handle connection status
  useEffect(() => {
    if (!isConnected) {
      setError('WebSocket disconnected. Waiting for reconnection...');
    } else {
      setError(null);
    }
  }, [isConnected]);

  // Handle WebSocket messages
  useEffect(() => {
    if (!socket) return;

    const handleMessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'account_update') {
          setAccounts(prevAccounts => {
            return prevAccounts.map(account => {
              if (account.account_no === data.account_no) {
                return { ...account, ...data.updates };
              }
              return account;
            });
          });
        }
      } catch (err) {
        console.error('Error processing message:', err);
      }
    };

    socket.addEventListener('message', handleMessage);

    return () => {
      socket.removeEventListener('message', handleMessage);
    };
  }, [socket]);

  const handleCopy = async (text, type) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedState(prev => ({ ...prev, [type]: true }));
      setTimeout(() => {
        setCopiedState(prev => ({ ...prev, [type]: false }));
      }, 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Render connection status
  const renderConnectionStatus = () => {
    if (!isConnected) {
      return (
        <Alert 
          severity="warning" 
          sx={{ mb: 2 }}
          action={
            connectionState === 'reconnecting' ? (
              <CircularProgress size={20} />
            ) : null
          }
        >
          {connectionState === 'reconnecting' 
            ? 'Reconnecting to WebSocket...' 
            : 'WebSocket is disconnected. Real-time updates may be delayed.'}
        </Alert>
      );
    }
    return null;
  };

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
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'multipart/form-data'
        },
        signal: controller.signal,
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

      // Handle successful response
      if (response.data) {
        const { total_imported, successful, failed, errors } = response.data;
        
        // Show final status
        setImportProgress({
          status: 'completed',
          percent: 100,
          message: `Import completed: ${successful} successful, ${failed} failed out of ${total_imported}`
        });

        if (successful > 0) {
          setSuccessMessage(`Successfully imported ${successful} accounts`);
          setTimeout(() => setSuccessMessage(null), 5000);
          await fetchAccounts(); // Refresh the accounts list
        }

        if (failed > 0 && errors?.length > 0) {
          setError(`Failed to import ${failed} accounts:\n${errors.join('\n')}`);
          setTimeout(() => setError(null), 10000);
        }
      }
      
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
      const res = await axios.post(`${API_BASE_URL}/accounts/validate/${account_no}`, null, {
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        }
      });
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
      const res = await axios.post(`${API_BASE_URL}/accounts/recover/${account_no}`, null, {
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        }
      });
      setSuccessMessage(`Recovery result for ${account_no}: ${res.data.recovery_result}`);
      setTimeout(() => setSuccessMessage(null), 5000);
    } catch (err) {
      setError(`Error recovering account ${account_no}: ${err.message}`);
      setTimeout(() => setError(null), 5000);
    }
    setRecovering(prev => ({...prev, [account_no]: false}));
  }

  async function handleRefreshCookies(account_no) {
    setRefreshing(prev => ({...prev, [account_no]: true}));
    try {
      const res = await axios.post(`${API_BASE_URL}/accounts/refresh-cookies/${account_no}`, null, {
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        }
      });
      if (res.data.success) {
        setSuccessMessage(`Successfully refreshed cookies for ${account_no}`);
        // Show cookies in dialog
        setCookieDialog({
          open: true,
          ct0: res.data.ct0,
          auth_token: res.data.auth_token
        });
        await fetchAccounts(); // Refresh the accounts list
      } else {
        throw new Error(res.data.error || 'Failed to refresh cookies');
      }
    } catch (err) {
      setError(`Error refreshing cookies for ${account_no}: ${err.message}`);
      setTimeout(() => setError(null), 5000);
    } finally {
      setRefreshing(prev => ({...prev, [account_no]: false}));
    }
  }

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
        headers: {
          'Accept': 'application/json',
          'Content-Type': 'application/json'
        },
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
      {renderConnectionStatus()}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" gutterBottom>Account Management</Typography>
        <HelpTooltip
          title="Account Management"
          content="Import and manage Twitter accounts. You can import accounts in bulk using CSV files, validate their status, and perform various operations."
          examples="account_no,login,password,email\nWACC001,user1,pass123,user1@email.com"
        />
      </Box>

      <InfoCard
        title="CSV Import Instructions"
        description="Import Twitter accounts using a CSV file. Each row represents one account with its configuration."
        requirements={[
          'CSV file with required columns',
          'UTF-8 encoding',
          'Maximum file size: 10MB',
          'One account per row'
        ]}
        validationRules={[
          'account_no must be unique',
          'login must be a valid Twitter username',
          'All proxy fields required if using proxy',
          'Valid email format required'
        ]}
        examples={[
          'account_no,login,password,email,proxy_url,proxy_port\nWACC001,user1,pass123,user1@email.com,proxy.example.com,8080'
        ]}
        templateUrl="/templates/accounts_template.csv"
      />
      
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
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <Typography variant="h6">Account Management</Typography>
              <HelpTooltip
                title="Bulk Operations"
                content="Perform operations on multiple accounts. Select accounts using checkboxes and use the buttons above to perform actions."
                placement="right"
              />
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
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
              <HelpTooltip
                title="Search"
                content="Search accounts by account number, login, or email. Updates results as you type."
                placement="left"
              />
            </Box>
          </Box>
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

            <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
              <Button
                variant="contained"
                color="error"
                onClick={async () => {
                  if (selectedAccounts.length === 0) {
                    setError('Please select accounts to delete');
                    setTimeout(() => setError(null), 5000);
                    return;
                  }
                  if (!confirm(`Are you sure you want to delete ${selectedAccounts.length} accounts?`)) {
                    return;
                  }
                  try {
                    await axios.post(
                      `${API_BASE_URL}/accounts/delete/bulk`,
                      { accounts: selectedAccounts }
                    );
                    setSuccessMessage(`Successfully deleted ${selectedAccounts.length} accounts`);
                    setTimeout(() => setSuccessMessage(null), 3000);
                    setSelectedAccounts([]);
                    await fetchAccounts();
                  } catch (err) {
                    setError(`Error deleting accounts: ${err.message}`);
                    setTimeout(() => setError(null), 5000);
                  }
                }}
                disabled={selectedAccounts.length === 0}
                startIcon={<DeleteIcon />}
              >
                Delete Selected
              </Button>
              <Button
                variant="contained"
                onClick={async () => {
                  if (selectedAccounts.length === 0) {
                    setError('Please select accounts to download');
                    setTimeout(() => setError(null), 5000);
                    return;
                  }
                  try {
                    const response = await axios.post(
                      `${API_BASE_URL}/accounts/setup/download`,
                      { accounts: selectedAccounts },
                      { responseType: 'blob' }
                    );
                    const url = window.URL.createObjectURL(new Blob([response.data]));
                    const link = document.createElement('a');
                    link.href = url;
                    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
                    link.setAttribute('download', `accounts_export_${timestamp}.csv`);
                    document.body.appendChild(link);
                    link.click();
                    link.remove();
                    window.URL.revokeObjectURL(url);
                    setSuccessMessage(`Successfully downloaded ${selectedAccounts.length} accounts`);
                    setTimeout(() => setSuccessMessage(null), 3000);
                  } catch (err) {
                    setError(`Error downloading accounts: ${err.message}`);
                    setTimeout(() => setError(null), 5000);
                  }
                }}
                disabled={selectedAccounts.length === 0}
                startIcon={<DownloadIcon />}
              >
                Download Selected
              </Button>
            </Box>
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', ml: 'auto' }}>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
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
                <HelpTooltip
                  title="Parallel Validation"
                  content="Number of accounts to validate simultaneously. Higher values are faster but use more resources."
                  placement="top"
                />
              </Box>
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
            {getCurrentPageAccounts().map(acc => (
              <TableRow key={acc.account_no}>
                <TableCell padding="checkbox">
                  <Checkbox
                    checked={selectedAccounts.includes(acc.account_no)}
                    onChange={e => {
                      if (e.target.checked) {
                        // Add this account to existing selections
                        setSelectedAccounts(prev => [...prev, acc.account_no]);
                      } else {
                        // Remove this account while keeping others
                        setSelectedAccounts(prev => prev.filter(no => no !== acc.account_no));
                      }
                    }}
                  />
                </TableCell>
                <TableCell>{acc.account_no}</TableCell>
                <TableCell>{acc.act_type}</TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    {acc.login && (
                      <>
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
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={async () => {
                            try {
                              const response = await axios.get(`${API_BASE_URL}/accounts/auth-url/${acc.account_no}`);
                              window.open(response.data.auth_url, '_blank', 'noopener,noreferrer');
                            } catch (err) {
                              setError(`Error opening authenticated session: ${err.message}`);
                              setTimeout(() => setError(null), 5000);
                            }
                          }}
                          sx={{ 
                            minWidth: 'auto',
                            fontSize: '0.75rem',
                            padding: '2px 8px'
                          }}
                        >
                          Open Authenticated
                        </Button>
                      </>
                    )}
                  </Box>
                </TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <Chip
                      label={acc.validation_in_progress || 'Not Started'}
                      color={getStatusColor(acc.validation_in_progress)}
                      size="small"
                    />
                    {acc.status_message && (
                      <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.75rem' }}>
                        {acc.status_message}
                      </Typography>
                    )}
                  </Box>
                </TableCell>
                <TableCell>
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    <Chip
                      label={acc.last_validation || 'Never'}
                      color={getStatusColor(acc.last_validation)}
                      size="small"
                    />
                  </Box>
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
                      color="primary"
                      onClick={() => handleRefreshCookies(acc.account_no)}
                      disabled={refreshing[acc.account_no]}
                      startIcon={refreshing[acc.account_no] ? <CircularProgress size={16} /> : <CookieIcon />}
                    >
                      {refreshing[acc.account_no] ? 'Refreshing...' : 'Refresh Cookies'}
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
            {[10, 25, 50, 100, 500, 1000, Infinity].map((n) => (
              <option key={n} value={n}>
                {n === Infinity ? 'All' : n}
              </option>
            ))}
          </select>
            <Typography variant="body2" color="text.secondary">
              (showing {rowsPerPage === Infinity ? totalAccounts : Math.min(rowsPerPage, accounts.length)} of {totalAccounts} accounts)
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
              onClick={() => setPage(p => Math.min(Math.ceil(totalAccounts / rowsPerPage) - 1, p + 1))}
              disabled={page >= Math.ceil(totalAccounts / rowsPerPage) - 1 || accounts.length === 0}
            >
              Next
            </Button>
          </Box>
        </Box>
      </Box>
      {/* Cookie Dialog */}
      <Dialog 
        open={cookieDialog.open} 
        onClose={() => setCookieDialog({ open: false, ct0: '', auth_token: '' })}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>New Cookies</DialogTitle>
        <DialogContent>
          <Box sx={{ mb: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mr: 1 }}>ct0:</Typography>
              <Typography 
                sx={{ 
                  flex: 1,
                  fontFamily: 'monospace',
                  bgcolor: 'grey.100',
                  p: 1,
                  borderRadius: 1
                }}
              >
                {cookieDialog.ct0}
              </Typography>
              <Tooltip title={copiedState.ct0 ? "Copied!" : "Copy ct0"}>
                <IconButton 
                  onClick={() => handleCopy(cookieDialog.ct0, 'ct0')}
                  color={copiedState.ct0 ? "success" : "default"}
                >
                  {copiedState.ct0 ? <CheckIcon /> : <CopyIcon />}
                </IconButton>
              </Tooltip>
            </Box>
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mr: 1 }}>auth_token:</Typography>
              <Typography 
                sx={{ 
                  flex: 1,
                  fontFamily: 'monospace',
                  bgcolor: 'grey.100',
                  p: 1,
                  borderRadius: 1
                }}
              >
                {cookieDialog.auth_token}
              </Typography>
              <Tooltip title={copiedState.auth_token ? "Copied!" : "Copy auth_token"}>
                <IconButton 
                  onClick={() => handleCopy(cookieDialog.auth_token, 'auth_token')}
                  color={copiedState.auth_token ? "success" : "default"}
                >
                  {copiedState.auth_token ? <CheckIcon /> : <CopyIcon />}
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCookieDialog({ open: false, ct0: '', auth_token: '' })}>
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
