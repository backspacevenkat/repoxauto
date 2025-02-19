import React, { useState, useEffect } from 'react';
import { 
    Card, 
    CardContent, 
    Typography, 
    Table, 
    TableBody, 
    TableCell, 
    TableContainer, 
    TableHead, 
    TableRow,
    Paper,
    LinearProgress,
    Chip,
    Stack,
    Box,
    Tooltip
} from '@mui/material';
import { useWebSocket } from './WebSocketProvider';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

const FollowPipelinePanel = () => {
    const [pipelineData, setPipelineData] = useState(null);
    const [loading, setLoading] = useState(true);
    const { lastMessage } = useWebSocket();

    // Fetch initial data
    useEffect(() => {
        fetchPipelineData();
        const interval = setInterval(fetchPipelineData, 30000); // Refresh every 30s
        return () => clearInterval(interval);
    }, []);

    // Update on websocket message
    useEffect(() => {
        if (lastMessage?.type === 'follow_stats') {
            setPipelineData(lastMessage.data);
        }
    }, [lastMessage]);

    const fetchPipelineData = async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/follow/stats`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'same-origin'
            });
            
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            setPipelineData(data);
            setLoading(false);
        } catch (error) {
            console.error('Error fetching follow pipeline data:', error);
            setLoading(false);
            // Show error in UI
            setPipelineData({
                error: true,
                message: `Failed to fetch system stats: ${error.message}`
            });
        }
    };

    if (loading) {
        return <Paper sx={{ p: 2 }}><LinearProgress /></Paper>;
    }

    if (pipelineData?.error) {
        return (
            <Paper sx={{ p: 2 }}>
                <Typography color="error" variant="body1">
                    {pipelineData.message}
                </Typography>
            </Paper>
        );
    }

    if (!pipelineData) {
        return (
            <Paper sx={{ p: 2 }}>
                <Typography variant="body1">
                    No data available
                </Typography>
            </Paper>
        );
    }

    const {
        total_accounts,
        active_accounts,
        rate_limited_accounts,
        total_internal,
        total_external,
        pending_internal,
        pending_external,
        follows_today,
        follows_this_interval,
        successful_follows,
        failed_follows,
        average_follows_per_hour,
        system_status
    } = pipelineData;

    const getStatusColor = (status) => {
        switch (status) {
            case 'active': return 'success';
            case 'pending': return 'default';
            case 'completed': return 'success';
            case 'failed': return 'error';
            case 'in_progress': return 'info';
            default: return 'default';
        }
    };

    return (
        <Stack spacing={3}>
            {/* System Overview */}
            <Card>
                <CardContent>
                    <Typography variant="h6" gutterBottom>System Overview</Typography>
                    <Stack spacing={3}>
                        {/* Status Overview */}
                        <Stack direction="row" spacing={2}>
                            <Tooltip title="Total accounts in system">
                                <Chip label={`Total Accounts: ${total_accounts}`} color="primary" />
                            </Tooltip>
                            <Tooltip title="Currently active accounts">
                                <Chip label={`Active: ${active_accounts}`} color="success" />
                            </Tooltip>
                            <Tooltip title="Rate limited accounts">
                                <Chip label={`Rate Limited: ${rate_limited_accounts}`} color="error" />
                            </Tooltip>
                        </Stack>

                        {/* Progress Overview */}
                        <Box>
                            <Typography variant="subtitle1" gutterBottom>Follow Progress</Typography>
                            <Stack direction="row" spacing={2}>
                                <Card variant="outlined" sx={{ p: 2, minWidth: 200 }}>
                                    <Typography variant="subtitle2">Current Progress</Typography>
                                    <Box sx={{ width: '100%', mt: 1 }}>
                                        <Typography variant="body2" color="text.secondary">
                                            Total Progress: {successful_follows}/{total_internal + total_external}
                                        </Typography>
                                        <LinearProgress 
                                            variant="determinate"
                                            value={Math.round((successful_follows / (total_internal + total_external)) * 100)}
                                            sx={{ mt: 1, mb: 1 }}
                                        />
                                        <Typography variant="caption" color="text.secondary">
                                            {Math.round((successful_follows / (total_internal + total_external)) * 100)}% Complete
                                        </Typography>
                                    </Box>
                                </Card>
                                <Card variant="outlined" sx={{ p: 2, minWidth: 200 }}>
                                    <Typography variant="subtitle2">Follow Rate</Typography>
                                    <Typography variant="h6">
                                        {Math.round(average_follows_per_hour)} follows/hour
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        {follows_this_interval} in last interval
                                    </Typography>
                                </Card>
                                <Card variant="outlined" sx={{ p: 2, minWidth: 200 }}>
                                    <Typography variant="subtitle2">Estimated Completion</Typography>
                                    <Typography variant="h6">
                                        {average_follows_per_hour > 0 ? 
                                            `${Math.round((total_internal + total_external - successful_follows) / average_follows_per_hour)}h` :
                                            'Calculating...'
                                        }
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        {pending_internal + pending_external} follows remaining
                                    </Typography>
                                </Card>
                            </Stack>
                        </Box>

                        {/* Schedule Info */}
                        <Box>
                            <Typography variant="subtitle1" gutterBottom>Current Schedule</Typography>
                            <Stack direction="row" spacing={2}>
                                <Card variant="outlined" sx={{ p: 2, minWidth: 200 }}>
                                    <Typography variant="subtitle2">Active Group</Typography>
                                    <Typography variant="h6">
                                        Group {system_status.active_group || '-'} of {system_status.total_groups}
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        {system_status.hours_per_group}h per group
                                    </Typography>
                                </Card>
                                <Card variant="outlined" sx={{ p: 2, minWidth: 200 }}>
                                    <Typography variant="subtitle2">Follow Intervals</Typography>
                                    <Typography variant="h6">
                                        {system_status.max_follows_per_interval} / {system_status.interval_minutes}min
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        15min minimum between follows
                                    </Typography>
                                </Card>
                                <Card variant="outlined" sx={{ p: 2, minWidth: 200 }}>
                                    <Typography variant="subtitle2">Next Group Start</Typography>
                                    <Typography variant="h6">
                                        {system_status.next_group_start ? 
                                            new Date(system_status.next_group_start).toLocaleTimeString() : 
                                            '-'
                                        }
                                    </Typography>
                                    <Typography variant="caption" color="text.secondary">
                                        System {system_status.is_active ? 'Active' : 'Inactive'}
                                    </Typography>
                                </Card>
                            </Stack>
                        </Box>
                    </Stack>
                </CardContent>
            </Card>

            {/* Active Accounts */}
            <Card>
                <CardContent>
                    <Typography variant="h6" gutterBottom>Active Accounts</Typography>
                    <TableContainer>
                        <Table>
                            <TableHead>
                                <TableRow>
                                    <TableCell>Account</TableCell>
                                    <TableCell>Status</TableCell>
                                    <TableCell>Daily Progress</TableCell>
                                    <TableCell>Following</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {pipelineData.accounts?.map((account) => (
                                    <TableRow key={account.id}>
                                        <TableCell>
                                            <Stack>
                                                <Typography>{account.login}</Typography>
                                                <Typography variant="caption" color="text.secondary">
                                                    Group {account.group || '-'} • Last Follow: {
                                                        account.last_followed_at ? 
                                                        new Date(account.last_followed_at).toLocaleTimeString() :
                                                        'Never'
                                                    }
                                                </Typography>
                                            </Stack>
                                        </TableCell>
                                        <TableCell>
                                            {account.is_rate_limited ? (
                                                <Tooltip title={`Rate limited until ${account.rate_limit_until}`}>
                                                    <Chip label="Rate Limited" color="error" size="small" />
                                                </Tooltip>
                                            ) : (
                                                <Chip 
                                                    label={account.status} 
                                                    color={getStatusColor(account.status)}
                                                    size="small"
                                                />
                                            )}
                                        </TableCell>
                                        <TableCell>
                                            <Box sx={{ width: '100%', mr: 1 }}>
                                                <Typography variant="body2" color="text.secondary">
                                                    Daily: {account.daily_follows}/{account.max_follows_per_day}
                                                </Typography>
                                                <LinearProgress
                                                    variant="determinate"
                                                    value={Math.round((account.daily_follows / account.max_follows_per_day) * 100)}
                                                    color={account.daily_follows >= account.max_follows_per_day ? "error" : "primary"}
                                                />
                                            </Box>
                                        </TableCell>
                                        <TableCell>
                                            <Box sx={{ width: '100%', mr: 1 }}>
                                                <Typography variant="body2" color="text.secondary">
                                                    Total: {account.following_count}/{account.max_following}
                                                </Typography>
                                                <LinearProgress
                                                    variant="determinate"
                                                    value={Math.round((account.following_count / account.max_following) * 100)}
                                                    color={account.following_count >= account.max_following ? "error" : "primary"}
                                                />
                                            </Box>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>
                </CardContent>
            </Card>

            {/* Follow Pipeline */}
            <Card>
                <CardContent>
                    <Typography variant="h6" gutterBottom>Follow Pipeline</Typography>
                    <Stack spacing={3}>
                        {/* In Progress Follows */}
                        <Box>
                            <Typography variant="subtitle1" gutterBottom color="primary">
                                In Progress Follows
                            </Typography>
                            <TableContainer>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Username</TableCell>
                                            <TableCell>Type</TableCell>
                                            <TableCell>Account</TableCell>
                                            <TableCell>Started At</TableCell>
                                            <TableCell>Status</TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {pipelineData.follow_pipeline?.filter(item => item.status === 'in_progress').map((item) => (
                                            <TableRow key={`${item.id}-${item.assigned_account}`}>
                                                <TableCell>{item.username}</TableCell>
                                                <TableCell>
                                                    <Chip 
                                                        label={item.list_type}
                                                        color={item.list_type === 'internal' ? 'primary' : 'secondary'}
                                                        size="small"
                                                    />
                                                </TableCell>
                                                <TableCell>{item.assigned_account}</TableCell>
                                                <TableCell>
                                                    {item.started_at ? 
                                                        new Date(item.started_at).toLocaleTimeString() :
                                                        '-'
                                                    }
                                                </TableCell>
                                                <TableCell>
                                                    <Chip 
                                                        label="In Progress"
                                                        color="info"
                                                        size="small"
                                                    />
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                        {!pipelineData.follow_pipeline?.some(item => item.status === 'in_progress') && (
                                            <TableRow>
                                                <TableCell colSpan={5} align="center">
                                                    <Typography variant="body2" color="text.secondary">
                                                        No follows currently in progress
                                                    </Typography>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        </Box>

                        {/* Upcoming Follows */}
                        <Box>
                            <Typography variant="subtitle1" gutterBottom color="secondary">
                                Upcoming Follows
                            </Typography>
                            <TableContainer>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Username</TableCell>
                                            <TableCell>Type</TableCell>
                                            <TableCell>Assigned To</TableCell>
                                            <TableCell>Scheduled For</TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {pipelineData.follow_pipeline?.filter(item => 
                                            item.status === 'pending' && item.scheduled_for
                                        ).sort((a, b) => 
                                            new Date(a.scheduled_for) - new Date(b.scheduled_for)
                                        ).slice(0, 5).map((item) => (
                                            <TableRow key={`${item.id}-${item.assigned_account}`}>
                                                <TableCell>{item.username}</TableCell>
                                                <TableCell>
                                                    <Chip 
                                                        label={item.list_type}
                                                        color={item.list_type === 'internal' ? 'primary' : 'secondary'}
                                                        size="small"
                                                    />
                                                </TableCell>
                                                <TableCell>{item.assigned_account || 'Unassigned'}</TableCell>
                                                <TableCell>
                                                    {item.scheduled_for ? 
                                                        new Date(item.scheduled_for).toLocaleTimeString() :
                                                        'Not scheduled'
                                                    }
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                        {!pipelineData.follow_pipeline?.some(item => 
                                            item.status === 'pending' && item.scheduled_for
                                        ) && (
                                            <TableRow>
                                                <TableCell colSpan={4} align="center">
                                                    <Typography variant="body2" color="text.secondary">
                                                        No scheduled follows
                                                    </Typography>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        </Box>

                        {/* Recent Completed/Failed */}
                        <Box>
                            <Typography variant="subtitle1" gutterBottom sx={{ color: theme => theme.palette.success.main }}>
                                Recently Completed
                            </Typography>
                            <TableContainer>
                                <Table>
                                    <TableHead>
                                        <TableRow>
                                            <TableCell>Username</TableCell>
                                            <TableCell>Type</TableCell>
                                            <TableCell>Account</TableCell>
                                            <TableCell>Completed At</TableCell>
                                            <TableCell>Next Follow</TableCell>
                                            <TableCell>Status</TableCell>
                                        </TableRow>
                                    </TableHead>
                                    <TableBody>
                                        {pipelineData.follow_pipeline?.filter(item => 
                                            item.status === 'completed' || item.status === 'failed'
                                        ).slice(0, 5).map((item) => (
                                            <TableRow key={`${item.id}-${item.assigned_account}`}>
                                                <TableCell>{item.username}</TableCell>
                                                <TableCell>
                                                    <Chip 
                                                        label={item.list_type}
                                                        color={item.list_type === 'internal' ? 'primary' : 'secondary'}
                                                        size="small"
                                                    />
                                                </TableCell>
                                                <TableCell>{item.assigned_account}</TableCell>
                                                <TableCell>
                                                    {item.followed_at ? 
                                                        new Date(item.followed_at).toLocaleTimeString() :
                                                        '-'
                                                    }
                                                </TableCell>
                                                <TableCell>
                                                    {item.next_follow ? 
                                                        new Date(item.next_follow).toLocaleTimeString() :
                                                        '-'
                                                    }
                                                </TableCell>
                                                <TableCell>
                                                    <Tooltip title={item.error || ''}>
                                                        <Chip 
                                                            label={item.status}
                                                            color={item.status === 'completed' ? 'success' : 'error'}
                                                            size="small"
                                                        />
                                                    </Tooltip>
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                        {!pipelineData.follow_pipeline?.some(item => 
                                            item.status === 'completed' || item.status === 'failed'
                                        ) && (
                                            <TableRow>
                                                <TableCell colSpan={6} align="center">
                                                    <Typography variant="body2" color="text.secondary">
                                                        No recently completed follows
                                                    </Typography>
                                                </TableCell>
                                            </TableRow>
                                        )}
                                    </TableBody>
                                </Table>
                            </TableContainer>
                        </Box>
                    </Stack>
                </CardContent>
            </Card>
        </Stack>
    );
};

export default FollowPipelinePanel;
