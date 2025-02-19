import React, { useState, useCallback, useEffect } from 'react';
import { useDropzone } from 'react-dropzone';
import { useWebSocket } from './WebSocketProvider';
import {
  Box,
  Button,
  Table,
  TableContainer,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Typography,
  Stack,
  Chip,
  LinearProgress,
  Select,
  MenuItem,
  IconButton,
  Tooltip,
  Link,
  Alert,
  AlertTitle,
  Paper
} from '@mui/material';
import {
  Download as DownloadIcon,
  Delete as DeleteIcon,
  Refresh as RefreshIcon
} from '@mui/icons-material';
import { useSnackbar } from 'notistack';

const ProfileUpdatesPanel = () => {
  const [updates, setUpdates] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const { enqueueSnackbar } = useSnackbar();
  const { socket } = useWebSocket();

  // Listen for WebSocket messages about profile update status changes
  useEffect(() => {
    if (!socket) return;

    const handleMessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'profile_update_status') {
          // Update the status in our local state
          setUpdates(prevUpdates => 
            prevUpdates.map(update => 
              update.id === data.profile_update_id 
                ? { ...update, status: data.status }
                : update
            )
          );
        }
      } catch (error) {
        console.error('Error handling WebSocket message:', error);
      }
    };

    socket.addEventListener('message', handleMessage);

    return () => {
      socket.removeEventListener('message', handleMessage);
    };
  }, [socket]);

  // Fetch updates on mount and when filter changes
  useEffect(() => {
    fetchUpdates();
  }, [filter]);

  const fetchUpdates = async () => {
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') {
        params.append('status', filter);
      }
      
      const response = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/profile-updates/list`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          skip: 0,
          limit: 100,
          status: filter !== 'all' ? filter : undefined
        })
      });
      if (!response.ok) throw new Error('Failed to fetch updates');
      
      const data = await response.json();
      setUpdates(data);
    } catch (error) {
      enqueueSnackbar(
        "Error fetching updates: " + error.message,
        { variant: 'error' }
      );
    } finally {
      setIsLoading(false);
    }
  };

  const onDrop = useCallback(async (acceptedFiles) => {
    const file = acceptedFiles[0];
    if (!file) return;

    if (!file.name.endsWith('.csv')) {
      enqueueSnackbar(
        "Please upload a CSV file",
        { variant: 'error' }
      );
      return;
    }

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/profile-updates/upload-csv`, {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (response.ok) {
        enqueueSnackbar(
          data.message,
          { variant: 'success' }
        );
        
        // Add new updates to the list
        setUpdates(prev => [...data.updates, ...prev]);

        // Show errors if any
        if (data.errors?.length) {
          enqueueSnackbar(
            `${data.errors.length} rows could not be processed`,
            { variant: 'warning' }
          );
        }
      } else {
        throw new Error(data.detail || 'Upload failed');
      }
    } catch (error) {
      enqueueSnackbar(
        "Upload failed: " + error.message,
        { variant: 'error' }
      );
    } finally {
      setIsUploading(false);
    }
  }, [enqueueSnackbar]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'text/csv': ['.csv'] },
    multiple: false
  });

  const handleDelete = async (id) => {
    try {
      // First get the update to verify it exists and is pending
      const getResponse = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/profile-updates/get/${id}`, {
        method: 'POST'
      });
      
      if (!getResponse.ok) {
        throw new Error('Update not found or not in pending state');
      }
      
      const update = await getResponse.json();
      if (update.status !== 'pending') {
        throw new Error('Only pending updates can be deleted');
      }
      
      // Then delete it
      const deleteResponse = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/profile-updates/${id}`, {
        method: 'DELETE'
      });

      if (deleteResponse.ok) {
        setUpdates(prev => prev.filter(update => update.id !== id));
        enqueueSnackbar(
          "Update deleted successfully",
          { variant: 'success' }
        );
      } else {
        throw new Error('Failed to delete update');
      }
    } catch (error) {
      enqueueSnackbar(
        "Delete failed: " + error.message,
        { variant: 'error' }
      );
    }
  };

  const downloadTemplate = () => {
    const headers = ['account_no', 'name', 'description', 'url', 'location', 'profile_image', 'profile_banner', 'lang'];
    const csvContent = "data:text/csv;charset=utf-8," + headers.join(',');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", "profile_updates_template.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const getStatusChip = (status) => {
    const statusColors = {
      pending: 'warning',
      processing: 'info',
      completed: 'success',
      failed: 'error'
    };

    return (
      <Chip
        label={status}
        color={statusColors[status] || 'default'}
        size="small"
      />
    );
  };

  return (
    <Stack spacing={2}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Button
          startIcon={<DownloadIcon />}
          onClick={downloadTemplate}
          size="small"
          variant="outlined"
        >
          Download Template
        </Button>
        <Select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          size="small"
          sx={{ width: 200 }}
        >
          <MenuItem value="all">All Status</MenuItem>
          <MenuItem value="pending">Pending</MenuItem>
          <MenuItem value="processing">Processing</MenuItem>
          <MenuItem value="completed">Completed</MenuItem>
          <MenuItem value="failed">Failed</MenuItem>
        </Select>
      </Box>

      <Paper
        {...getRootProps()}
        sx={{
          p: 3,
          border: '2px dashed',
          borderColor: isDragActive ? 'primary.main' : 'grey.300',
          borderRadius: 1,
          textAlign: 'center',
          cursor: 'pointer',
          '&:hover': {
            borderColor: 'primary.main'
          }
        }}
      >
        <input {...getInputProps()} />
        <Typography>
          {isDragActive
            ? "Drop the CSV file here"
            : "Drag and drop a CSV file here, or click to select"}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Supported fields: account_no (required), name, description, url, location, profile_image, profile_banner, lang
        </Typography>
      </Paper>

      {isUploading && <LinearProgress />}

      {isLoading ? (
        <LinearProgress />
      ) : updates.length === 0 ? (
        <Alert severity="info">
          <AlertTitle>No profile updates found</AlertTitle>
        </Alert>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Account</TableCell>
                <TableCell>Name</TableCell>
                <TableCell>Description</TableCell>
                <TableCell>Location</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {updates.map((update) => (
                <TableRow key={update.id}>
                  <TableCell>{update.account_no}</TableCell>
                  <TableCell>{update.name || '-'}</TableCell>
                  <TableCell sx={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {update.description || '-'}
                  </TableCell>
                  <TableCell>{update.location || '-'}</TableCell>
                  <TableCell>{getStatusChip(update.status)}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1}>
                      {update.status === 'pending' && (
                        <Tooltip title="Delete">
                          <IconButton
                            size="small"
                            color="error"
                            onClick={() => handleDelete(update.id)}
                          >
                            <DeleteIcon />
                          </IconButton>
                        </Tooltip>
                      )}
                      <Tooltip title="Refresh">
                          <IconButton
                            size="small"
                            color="primary"
                            onClick={() => fetchUpdates()}
                          >
                            <RefreshIcon />
                          </IconButton>
                      </Tooltip>
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Stack>
  );
};

export default ProfileUpdatesPanel;
