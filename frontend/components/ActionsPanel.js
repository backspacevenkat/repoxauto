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
    Input,
    Menu,
    MenuItem
} from '@mui/material';
import {
    Upload as UploadIcon,
    Refresh as RefreshIcon,
    Download as DownloadIcon,
    PlayArrow as PlayArrowIcon,
    Stop as StopIcon,
    Info as InfoIcon,
    MoreVert as MoreVertIcon,
    Person as PersonIcon
} from '@mui/icons-material';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

const ActionsPanel = () => {
    const [file, setFile] = useState(null);
    const [loading, setLoading] = useState(false);
    const [accountLoading, setAccountLoading] = useState({});
    const [menuAnchor, setMenuAnchor] = useState(null);
    const [selectedAccount, setSelectedAccount] = useState(null);
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
            const response = await fetch(`${API_BASE_URL}/actions/list`);
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

    const handleMenuOpen = (event, account) => {
        setMenuAnchor(event.currentTarget);
        setSelectedAccount(account);
    };

    const handleMenuClose = () => {
        setMenuAnchor(null);
        setSelectedAccount(null);
    };

    const validateAccount = async (accountNo) => {
        try {
            setAccountLoading(prev => ({ ...prev, [accountNo]: 'validating' }));
            const response = await fetch(`${API_BASE_URL}/accounts/${accountNo}/validate`, {
                method: 'POST'
            });
            
            if (!response.ok) {
                throw new Error('Validation failed');
            }
            
            const data = await response.json();
            setError(null);
            
            fetchActions();
            
        } catch (error) {
            console.error('Validation error:', error);
            setError(`Validation failed: ${error.message}`);
        } finally {
            setAccountLoading(prev => ({ ...prev, [accountNo]: false }));
            handleMenuClose();
        }
    };

    const refreshCookies = async (accountNo) => {
        try {
            setAccountLoading(prev => ({ ...prev, [accountNo]: 'refreshing' }));
            const response = await fetch(`${API_BASE_URL}/accounts/${accountNo}/refresh-cookies`, {
                method: 'POST'
            });
            
            if (!response.ok) {
                throw new Error('Cookie refresh failed');
            }
            
            const data = await response.json();
            setError(null);
            
            fetchActions();
            
        } catch (error) {
            console.error('Cookie refresh error:', error);
            setError(`Cookie refresh failed: ${error.message}`);
        } finally {
            setAccountLoading(prev => ({ ...prev, [accountNo]: false }));
            handleMenuClose();
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
            // Log the file being uploaded for debugging
            console.log('Uploading file:', file.name, 'Size:', file.size);

            const response = await fetch(`${API_BASE_URL}/actions/import`, {
                method: 'POST',
                body: formData,
            });

            // Log the raw response for debugging
            console.log('Response status:', response.status);
            const responseText = await response.text();
            console.log('Response text:', responseText);

            let result;
            try {
                result = JSON.parse(responseText);
            } catch (parseError) {
                console.error('Error parsing response:', parseError);
                throw new Error('Invalid response format from server');
            }

            if (!response.ok) {
                throw new Error(result.detail || result.message || 'Upload failed');
            }

            // Log successful result
            console.log('Upload result:', result);

            if (result.tasks_created === 0 && (!result.errors || result.errors.length === 0)) {
                setError('No actions were created. Please check your CSV file format.');
                return;
            }

            setUploadResult({
                successful: result.tasks_created || 0,
                failed: (result.errors || []).length,
                errors: result.errors || []
            });
            
            fetchActions();
        } catch (err) {
            console.error('Upload error:', err);
            setError(`Upload failed: ${err.message}`);
        } finally {
            setFile(null);
            setLoading(false);
            const fileInput = document.querySelector('input[type="file"]');
            if (fileInput) {
                const newInput = document.createElement('input');
                newInput.type = 'file';
                newInput.accept = '.csv';
                newInput.className = fileInput.className;
                newInput.addEventListener('change', handleFileChange);
                fileInput.parentNode.replaceChild(newInput, fileInput);
            }
        }
    };

    const handleRetry = async (actionId) => {
        try {
            const response = await fetch(`${API_BASE_URL}/actions/${actionId}/retry`, {
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
            const response = await fetch(`${API_BASE_URL}/actions/${actionId}/cancel`, {
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
                        Full CSV Format (with all columns):
                        account_no,task_type,source_tweet,text_content,media,api_method,user,priority
                        act203,like,https://x.com/user/status/123456789,,,graphql,,0
                        act204,RT,https://x.com/user/status/123456789,,,rest,,0
                        act205,follow,,,,graphql,elonmusk,0

                        Minimal CSV Format (for follow actions):
                        account_no,task_type,user
                        WACC162,follow,PayomDousti
                        WACC163,follow,mogmachine
                        
                        Notes:
                        • task_type can be: like, RT, reply, quote, post, follow
                        • text_content is required for reply, quote, and post
                        • media is optional
                        • api_method column is optional (defaults to graphql if missing)
                        • user is required for follow actions (only used with task_type=follow)
                        • priority is optional (default: 0)
                        • For follow actions: only account_no, task_type, and user are required
                        • For follow actions: source_tweet, text_content, and media should be empty
                        
                        You can find a sample file at: account_actions.csv
                    </Alert>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Box sx={{ flex: 1 }}>
                            <Input
                                type="file"
                                onChange={handleFileChange}
                                disabled={loading}
                                sx={{ width: '100%' }}
                                inputProps={{ accept: '.csv' }}
                                key={loading ? 'loading' : 'not-loading'}
                            />
                        </Box>
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
                            severity={uploadResult.failed > 0 ? "warning" : "success"}
                            onClose={() => setUploadResult(null)}
                        >
                            <Typography>Successfully created {uploadResult.successful} actions</Typography>
                            {uploadResult.failed > 0 && uploadResult.errors && (
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
                                <TableCell>Target Account</TableCell>
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
                                    <TableCell>
                                        <Stack direction="row" spacing={1} alignItems="center">
                                            <Typography>{action.account_id}</Typography>
                                            <IconButton
                                                size="small"
                                                onClick={(e) => handleMenuOpen(e, action.account_id)}
                                                disabled={accountLoading[action.account_id]}
                                            >
                                                {accountLoading[action.account_id] ? (
                                                    <CircularProgress size={20} />
                                                ) : (
                                                    <MoreVertIcon fontSize="small" />
                                                )}
                                            </IconButton>
                                        </Stack>
                                    </TableCell>
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
                                        {action.action_type !== 'follow_user' && (
                                            <Stack spacing={1}>
                                                {/* Source Tweet Link */}
                                                {(action.source_tweet || action.tweet_url) && (
                                                    <Tooltip title={action.source_tweet || action.tweet_url}>
                                                        <Typography 
                                                            component="a" 
                                                            href={action.source_tweet || action.tweet_url} 
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            sx={{ 
                                                                maxWidth: 200,
                                                                textDecoration: 'none',
                                                                color: 'primary.main',
                                                                '&:hover': { textDecoration: 'underline' }
                                                            }}
                                                            noWrap
                                                        >
                                                            Source Tweet
                                                        </Typography>
                                                    </Tooltip>
                                                )}
                                                
                                                {/* Result Tweet Link */}
                                                {action.status === 'completed' && (
                                                    action.result_tweet_url || 
                                                    action.result_tweet || 
                                                    (action.result && action.result.tweet_url) ||
                                                    (action.result && action.result.result && action.result.result.tweet_url)
                                                ) && (
                                                    <Tooltip title="View Result">
                                                        <Typography 
                                                            component="a" 
                                                            href={
                                                                action.result_tweet_url || 
                                                                action.result_tweet || 
                                                                (action.result && action.result.tweet_url) ||
                                                                (action.result && action.result.result && action.result.result.tweet_url)
                                                            }
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            sx={{ 
                                                                maxWidth: 200,
                                                                textDecoration: 'none',
                                                                color: 'success.main',
                                                                '&:hover': { textDecoration: 'underline' }
                                                            }}
                                                            noWrap
                                                        >
                                                            {action.action_type === 'retweet' ? 'View Retweet' : 
                                                             action.action_type === 'reply' ? 'View Reply' : 
                                                             action.action_type === 'quote' ? 'View Quote' : 
                                                             action.action_type === 'like' ? 'View Like' :
                                                             'View Result'}
                                                        </Typography>
                                                    </Tooltip>
                                                )}
                                            </Stack>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        {action.action_type === 'follow_user' && action.meta_data?.user && (
                                            <Stack direction="row" spacing={1} alignItems="center">
                                                <PersonIcon fontSize="small" color="action" />
                                                <Tooltip title={`@${action.meta_data.user}`}>
                                                    <Typography 
                                                        component="a" 
                                                        href={`https://twitter.com/${action.meta_data.user}`}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        sx={{ 
                                                            maxWidth: 200,
                                                            textDecoration: 'none',
                                                            color: 'primary.main',
                                                            '&:hover': { textDecoration: 'underline' }
                                                        }}
                                                        noWrap
                                                    >
                                                        @{action.meta_data.user}
                                                    </Typography>
                                                </Tooltip>
                                            </Stack>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <Tooltip title={action.error_message || ''}>
                                            <Chip
                                                label={action.status}
                                                color={action.result_tweet_url && ['reply_tweet', 'quote_tweet'].includes(action.action_type) ? 'success' : getStatusColor(action.status)}
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

            {/* Account Actions Menu */}
            <Menu
                anchorEl={menuAnchor}
                open={Boolean(menuAnchor)}
                onClose={handleMenuClose}
            >
                <MenuItem 
                    onClick={() => validateAccount(selectedAccount)}
                    disabled={accountLoading[selectedAccount] === 'validating'}
                >
                    <Stack direction="row" spacing={1} alignItems="center">
                        <PlayArrowIcon fontSize="small" />
                        <Typography>
                            {accountLoading[selectedAccount] === 'validating' ? 'Validating...' : 'Validate Account'}
                        </Typography>
                    </Stack>
                </MenuItem>
                <MenuItem 
                    onClick={() => refreshCookies(selectedAccount)}
                    disabled={accountLoading[selectedAccount] === 'refreshing'}
                >
                    <Stack direction="row" spacing={1} alignItems="center">
                        <RefreshIcon fontSize="small" />
                        <Typography>
                            {accountLoading[selectedAccount] === 'refreshing' ? 'Refreshing...' : 'Refresh Cookies'}
                        </Typography>
                    </Stack>
                </MenuItem>
            </Menu>

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
