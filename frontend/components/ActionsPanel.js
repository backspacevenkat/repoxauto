import React, { useState, useEffect } from 'react';
import { useWebSocket } from './WebSocketProvider';
import TaskDetailsModal from './TaskDetailsModal';
import {
    Box,
    Button,
    Typography,
    Paper,
    CircularProgress,
    Alert,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Chip,
    IconButton,
    Tooltip,
    Container,
    Input
} from '@mui/material';
import {
    Upload as UploadIcon,
    Refresh as RefreshIcon,
    Download as DownloadIcon,
    PlayArrow as PlayArrowIcon,
    Stop as StopIcon,
    Info as InfoIcon
} from '@mui/icons-material';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

const ActionsPanel = () => {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [actions, setActions] = useState([]);
    const [uploadResult, setUploadResult] = useState(null);
    const [selectedActionId, setSelectedActionId] = useState(null);
    const { socket, isConnected } = useWebSocket();

    useEffect(() => {
        fetchActions();

        if (socket) {
            const handleMessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.type === 'action_update') {
                        fetchActions();
                    }
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            socket.addEventListener('message', handleMessage);
            return () => socket.removeEventListener('message', handleMessage);
        }
    }, [socket, isConnected]);

    const fetchActions = async () => {
        try {
            const response = await fetch(`${BACKEND_URL}/actions/list`);
            if (!response.ok) {
                throw new Error(`Failed to fetch actions: ${response.statusText}`);
            }
            const data = await response.json();
            setActions(data);
        } catch (err) {
            console.error('Error fetching actions:', err);
            setError('Failed to fetch actions');
        }
    };

    const handleFileChange = (event) => {
        const selectedFile = event.target.files[0];
        if (selectedFile && selectedFile.name.endsWith('.csv')) {
            setFile(selectedFile);
            setError(null);
        } else {
            setError('Please select a CSV file');
            setFile(null);
        }
    };

    const handleUpload = async () => {
        if (!file) {
            setError('Please select a file first');
            return;
        }

        setLoading(true);
        setError(null);
        setUploadResult(null);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(`${BACKEND_URL}/actions/import`, {
                method: 'POST',
                body: formData,
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Upload failed');
            }

            setUploadResult(result);
            fetchActions();
            setFile(null);
            // Reset file input
            const fileInput = document.querySelector('input[type="file"]');
            if (fileInput) fileInput.value = '';
        } catch (err) {
            console.error('Upload error:', err);
            setError(`Upload failed: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    const handleRetry = async (actionId) => {
        try {
            const response = await fetch(`${BACKEND_URL}/actions/${actionId}/retry`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error('Retry failed');
            }

            fetchActions();
        } catch (err) {
            console.error('Retry error:', err);
            setError(`Failed to retry action: ${err.message}`);
        }
    };

    const handleCancel = async (actionId) => {
        try {
            const response = await fetch(`${BACKEND_URL}/actions/${actionId}/cancel`, {
                method: 'POST'
            });

            if (!response.ok) {
                throw new Error('Cancel failed');
            }

            fetchActions();
        } catch (err) {
            console.error('Cancel error:', err);
            setError(`Failed to cancel action: ${err.message}`);
        }
    };

    const getStatusColor = (status) => {
        switch (status) {
            case 'pending':
                return 'warning';
            case 'running':
                return 'info';
            case 'completed':
                return 'success';
            case 'failed':
                return 'error';
            case 'cancelled':
                return 'default';
            default:
                return 'default';
        }
    };

    const formatDateTime = (dateStr) => {
        if (!dateStr) return '';
        return new Date(dateStr).toLocaleString();
    };

    return (
        <Container maxWidth="xl">
            {/* Upload Section */}
            <Paper sx={{ p: 2, mb: 3 }}>
                <Stack spacing={2}>
                    <Typography variant="h6">Upload Actions CSV</Typography>
                    <Alert severity="info" sx={{ whiteSpace: 'pre-wrap' }}>
                        CSV Format Example:
                        account_no,task_type,source_tweet,text_content,media,api_method
                        act203,like,https://x.com/user/status/123456789,,,graphql
                        act204,RT,https://x.com/user/status/123456789,,,rest
                        
                        Notes:
                        • task_type can be: like, RT, reply, quote, post
                        • text_content is required for reply, quote, and post
                        • media is optional
                        • api_method can be: graphql or rest (default: graphql)
                        • Priority is optional (default: 0)
                        
                        You can find a sample file at: account_actions.csv
                    </Alert>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Input
                            type="file"
                            onChange={handleFileChange}
                            disabled={loading}
                            sx={{ flex: 1 }}
                            inputProps={{ accept: '.csv' }}
                        />
                        <Button
                            variant="contained"
                            onClick={handleUpload}
                            disabled={!file || loading}
                            startIcon={loading ? <CircularProgress size={20} /> : <UploadIcon />}
                        >
                            {loading ? 'Uploading...' : 'Upload'}
                        </Button>
                        <Tooltip title="Refresh actions">
                            <IconButton onClick={fetchActions} disabled={loading}>
                                <RefreshIcon />
                            </IconButton>
                        </Tooltip>
                    </Box>
                    {error && (
                        <Alert severity="error" onClose={() => setError(null)}>
                            {error}
                        </Alert>
                    )}
                    {uploadResult && (
                        <Alert 
                            severity={uploadResult.errors?.length > 0 ? "warning" : "success"}
                            onClose={() => setUploadResult(null)}
                        >
                            <Typography>Successfully created {uploadResult.tasks_created} actions</Typography>
                            {uploadResult.errors?.length > 0 && (
                                <Box sx={{ mt: 1 }}>
                                    <Typography variant="subtitle2">Errors:</Typography>
                                    {uploadResult.errors.map((error, index) => (
                                        <Typography key={index} variant="body2" color="error">
                                            • {error}
                                        </Typography>
                                    ))}
                                </Box>
                            )}
                        </Alert>
                    )}
                </Stack>
            </Paper>

            {/* Actions Table */}
            <Paper sx={{ p: 2 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                    <Typography variant="h6">Actions</Typography>
                    <Chip 
                        label={`${actions.length} actions`}
                        color="primary"
                        variant="outlined"
                    />
                </Stack>
                <TableContainer>
                    <Table>
                        <TableHead>
                            <TableRow>
                                <TableCell>ID</TableCell>
                                <TableCell>Account</TableCell>
                                <TableCell>Type</TableCell>
                                <TableCell>API Method</TableCell>
                                <TableCell>Tweet URL</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Created</TableCell>
                                <TableCell>Executed</TableCell>
                                <TableCell>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {actions.map((action) => (
                                <TableRow key={action.id}>
                                    <TableCell>{action.id}</TableCell>
                                    <TableCell>{action.account_id}</TableCell>
                                    <TableCell>{action.action_type}</TableCell>
                                    <TableCell>
                                        <Chip
                                            label={action.api_method || 'graphql'}
                                            size="small"
                                            variant="outlined"
                                            color={action.api_method === 'rest' ? 'secondary' : 'primary'}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <Stack spacing={1}>
                                            <Tooltip title={action.tweet_url}>
                                                <Typography 
                                                    component="a" 
                                                    href={action.tweet_url} 
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    sx={{ 
                                                        maxWidth: 200,
                                                        textDecoration: 'none',
                                                        color: 'primary.main',
                                                        '&:hover': {
                                                            textDecoration: 'underline'
                                                        }
                                                    }}
                                                    noWrap
                                                >
                                                    {action.action_type === 'like' ? 'View Tweet' : 'Source Tweet'}
                                                </Typography>
                                            </Tooltip>
                                            {action.status === 'completed' && (
                                                <Tooltip title="View Result">
                                                    <Typography 
                                                        component="a" 
                                                        href={`https://twitter.com/${action.account_id}`}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        sx={{ 
                                                            maxWidth: 200,
                                                            textDecoration: 'none',
                                                            color: 'secondary.main',
                                                            '&:hover': {
                                                                textDecoration: 'underline'
                                                            }
                                                        }}
                                                        noWrap
                                                    >
                                                        {action.action_type === 'RT' ? 'View Retweet' : 
                                                         action.action_type === 'reply' ? 'View Reply' : 
                                                         action.action_type === 'quote' ? 'View Quote' : 
                                                         'View Result'}
                                                    </Typography>
                                                </Tooltip>
                                            )}
                                        </Stack>
                                    </TableCell>
                                    <TableCell>
                                        <Tooltip title={action.error_message || ''}>
                                            <Chip
                                                label={action.status}
                                                color={getStatusColor(action.status)}
                                                size="small"
                                            />
                                        </Tooltip>
                                    </TableCell>
                                    <TableCell>{formatDateTime(action.created_at)}</TableCell>
                                    <TableCell>{formatDateTime(action.executed_at)}</TableCell>
                                    <TableCell>
                                        <Stack direction="row" spacing={1}>
                                            <Tooltip title="View Details">
                                                <IconButton
                                                    size="small"
                                                    onClick={() => setSelectedActionId(action.id)}
                                                    color="info"
                                                >
                                                    <InfoIcon />
                                                </IconButton>
                                            </Tooltip>
                                            {action.status === 'failed' && (
                                                <Tooltip title="Retry">
                                                    <IconButton
                                                        size="small"
                                                        onClick={() => handleRetry(action.id)}
                                                        color="primary"
                                                    >
                                                        <PlayArrowIcon />
                                                    </IconButton>
                                                </Tooltip>
                                            )}
                                            {action.status === 'pending' && (
                                                <Tooltip title="Cancel">
                                                    <IconButton
                                                        size="small"
                                                        onClick={() => handleCancel(action.id)}
                                                        color="error"
                                                    >
                                                        <StopIcon />
                                                    </IconButton>
                                                </Tooltip>
                                            )}
                                        </Stack>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            </Paper>

            {/* Action Details Modal */}
            <TaskDetailsModal
                open={!!selectedActionId}
                onClose={() => setSelectedActionId(null)}
                taskId={selectedActionId}
            />
        </Container>
    );
};

export default ActionsPanel;
