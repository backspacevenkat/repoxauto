import React, { useState, useEffect } from 'react';
import {
  Box,
  Card,
  CardContent,
  Grid,
  Typography,
  CircularProgress,
  Button,
  Alert,
  Chip,
  LinearProgress,
  Stack,
  Tooltip
} from '@mui/material';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import GroupIcon from '@mui/icons-material/Group';
import { format } from 'date-fns';

export default function FollowSystemStats() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [systemAction, setSystemAction] = useState(null);

  useEffect(() => {
    fetchStats();
    const interval = setInterval(fetchStats, 30000); // Update every 30 seconds
    return () => clearInterval(interval);
  }, []);

  const fetchStats = async () => {
    try {
      const response = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/follow/stats`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        credentials: 'same-origin'
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || 'Failed to fetch stats');
      }
      
      const data = await response.json();
      if (data.detail) {
        throw new Error(data.detail);
      }
      setStats(data);
      setError(null);
    } catch (error) {
      console.error('Error fetching stats:', error);
      setError(`Failed to fetch system stats: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleStartStop = async (action) => {
    setSystemAction(action);
    try {
      const response = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/follow/${action}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        credentials: 'same-origin'
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || `Failed to ${action} system`);
      }
      
      // For stop action, also call reconfigure
      if (action === 'stop') {
        const reconfigureResponse = await fetch(`${(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api'}/follow/reconfigure`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          },
          credentials: 'same-origin'
        });
        
        if (!reconfigureResponse.ok) {
          console.warn('Failed to reconfigure system after stop');
        }
      }
      
      // Fetch fresh stats
      await fetchStats();
      setError(null);
    } catch (error) {
      console.error(`Error ${action}ing system:`, error);
      setError(`Failed to ${action} system: ${error.message}`);
    } finally {
      setSystemAction(null);
    }
  };

  if (loading && !stats) {
    return (
      <Card>
        <CardContent>
          <Box display="flex" justifyContent="center" alignItems="center" minHeight={200}>
            <CircularProgress />
          </Box>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={3}>
          <Typography variant="h5">
            Follow System Status
          </Typography>
          <Box>
            <Button
              variant="contained"
              color="success"
              startIcon={<PlayArrowIcon />}
              onClick={() => handleStartStop('start')}
              disabled={systemAction === 'start' || (stats?.system_status?.is_active)}
              sx={{ mr: 1 }}
            >
              Start
            </Button>
            <Button
              variant="contained"
              color="error"
              startIcon={<StopIcon />}
              onClick={() => handleStartStop('stop')}
              disabled={systemAction === 'stop' || (!stats?.system_status?.is_active)}
            >
              Stop
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}

        {stats && (
          <Grid container spacing={3}>
            {/* System Status */}
            <Grid item xs={12}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>System Overview</Typography>
                  <Stack direction="row" spacing={2} mb={2}>
                    <Tooltip title="Total accounts in system">
                      <Chip label={`Total Accounts: ${stats.total_accounts}`} color="primary" />
                    </Tooltip>
                    <Tooltip title="Currently active accounts">
                      <Chip label={`Active: ${stats.active_accounts}`} color="success" />
                    </Tooltip>
                    <Tooltip title="Rate limited accounts">
                      <Chip label={`Rate Limited: ${stats.rate_limited_accounts}`} color="error" />
                    </Tooltip>
                    <Chip 
                      label={stats.system_status.is_active ? "System Active" : "System Inactive"}
                      color={stats.system_status.is_active ? "success" : "default"}
                    />
                  </Stack>
                  
                  <Grid container spacing={2}>
                    <Grid item xs={12} md={4}>
                      <Card variant="outlined">
                        <CardContent>
                          <Typography variant="subtitle2">Follow Rate</Typography>
                          <Typography variant="h6">
                            {Math.round(stats.average_follows_per_hour)} follows/hour
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {stats.follows_this_interval} in last interval
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid item xs={12} md={4}>
                      <Card variant="outlined">
                        <CardContent>
                          <Typography variant="subtitle2">Success Rate</Typography>
                          <Typography variant="h6">
                            {stats.average_success_rate}%
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {stats.successful_follows} successful / {stats.failed_follows} failed
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid item xs={12} md={4}>
                      <Card variant="outlined">
                        <CardContent>
                          <Typography variant="subtitle2">Estimated Completion</Typography>
                          <Typography variant="h6">
                            {stats.average_follows_per_hour > 0 ? 
                              `${Math.round((stats.total_internal + stats.total_external - stats.successful_follows) / stats.average_follows_per_hour)}h` :
                              'Calculating...'
                            }
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {stats.pending_internal + stats.pending_external} follows remaining
                          </Typography>
                        </CardContent>
                      </Card>
                    </Grid>
                  </Grid>
                </CardContent>
              </Card>
            </Grid>

            {/* Follow Progress */}
            <Grid item xs={12} md={6}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>Follow Progress</Typography>
                  <Stack spacing={2}>
                    <Box>
                      <Typography variant="subtitle2" gutterBottom>Internal Follows</Typography>
                      <Box display="flex" justifyContent="space-between" mb={1}>
                        <Typography variant="body2">Progress:</Typography>
                        <Typography variant="body2">
                          {stats.successful_follows} / {stats.total_internal}
                        </Typography>
                      </Box>
                      <LinearProgress 
                        variant="determinate" 
                        value={(stats.successful_follows / stats.total_internal) * 100}
                      />
                    </Box>
                    <Box>
                      <Typography variant="subtitle2" gutterBottom>External Follows</Typography>
                      <Box display="flex" justifyContent="space-between" mb={1}>
                        <Typography variant="body2">Progress:</Typography>
                        <Typography variant="body2">
                          {stats.successful_follows} / {stats.total_external}
                        </Typography>
                      </Box>
                      <LinearProgress 
                        variant="determinate" 
                        value={(stats.successful_follows / stats.total_external) * 100}
                      />
                    </Box>
                  </Stack>
                </CardContent>
              </Card>
            </Grid>

            {/* Schedule Info */}
            <Grid item xs={12} md={6}>
              <Card variant="outlined">
                <CardContent>
                  <Typography variant="h6" gutterBottom>Schedule Status</Typography>
                  <Grid container spacing={2}>
                    <Grid item xs={12}>
                      <Box display="flex" alignItems="center" mb={2}>
                        <GroupIcon sx={{ mr: 1 }} />
                        <Typography>
                          Active Group: {stats.active_group || 'None'} of {stats.system_status.total_groups}
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid item xs={12}>
                      <Box display="flex" alignItems="center" mb={2}>
                        <AccessTimeIcon sx={{ mr: 1 }} />
                        <Typography>
                          Next Group Start: {stats.next_group_start ? 
                            format(new Date(stats.next_group_start), 'HH:mm:ss') : 
                            'Not Scheduled'
                          }
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid item xs={12}>
                      <Typography variant="subtitle2" gutterBottom>Follow Intervals</Typography>
                      <Box display="flex" alignItems="center">
                        <Chip 
                          label={`${stats.system_status.max_follows_per_interval} follow per ${stats.system_status.interval_minutes}min`}
                          color="primary"
                          sx={{ mr: 1 }}
                        />
                        <Chip 
                          label={`${stats.follows_today} follows today`}
                          color="secondary"
                        />
                      </Box>
                    </Grid>
                  </Grid>
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        )}
      </CardContent>
    </Card>
  );
}
