import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  TextField,
  Button,
  Stack,
  Alert,
  Paper,
  Grid,
  Chip,
  Divider
} from '@mui/material';
import axios from 'axios';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

const WorkerSettings = () => {
  const [settings, setSettings] = useState({
    maxConcurrentWorkers: 12,
    maxRequestsPerWorker: 900,
    requestInterval: 60
  });
  const [status, setStatus] = useState({
    total_workers: 0,
    active_workers: 0,
    completed_tasks: 0,
    pending_tasks: 0,
    worker_utilization: {}
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [settingsRes, statusRes] = await Promise.all([
        axios.get(`${API_BASE_URL}/settings/`),
        axios.get(`${API_BASE_URL}/tasks/stats`)
      ]);
      setSettings({
        maxConcurrentWorkers: settingsRes.data.max_concurrent_workers,
        maxRequestsPerWorker: settingsRes.data.max_requests_per_worker,
        requestInterval: settingsRes.data.request_interval
      });
      setStatus(statusRes.data);
    } catch (error) {
      setError(error.response?.data?.detail || 'Failed to fetch data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // Refresh every minute
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, []);

  const updateSettings = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);
      await axios.post(`${API_BASE_URL}/settings/`, {
        max_concurrent_workers: settings.maxConcurrentWorkers,
        max_requests_per_worker: settings.maxRequestsPerWorker,
        request_interval: settings.requestInterval
      });
      setSuccess('Settings updated successfully');
      fetchData();
    } catch (error) {
      setError(error.response?.data?.detail || 'Failed to update settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Paper sx={{ p: 3, mt: 3 }}>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {success && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {success}
        </Alert>
      )}

      <Stack spacing={3}>
        <TextField
          label="Max Concurrent Workers"
          type="number"
          value={settings.maxConcurrentWorkers}
          onChange={(e) => {
            const value = e.target.value === '' ? '' : parseInt(e.target.value);
            if (value === '' || (value >= 1 && value <= 100)) {
              setSettings({ ...settings, maxConcurrentWorkers: value });
            }
          }}
          onBlur={() => {
            if (settings.maxConcurrentWorkers === '' || settings.maxConcurrentWorkers < 1) {
              setSettings({ ...settings, maxConcurrentWorkers: 1 });
            }
          }}
          error={settings.maxConcurrentWorkers === '' || settings.maxConcurrentWorkers < 1}
          helperText="Maximum number of workers that can run simultaneously"
          InputProps={{ inputProps: { min: 1 } }}
          fullWidth
        />

        <TextField
          label="Max Requests per Worker (15min)"
          type="number"
          value={settings.maxRequestsPerWorker}
          onChange={(e) => {
            const value = e.target.value === '' ? '' : parseInt(e.target.value);
            if (value === '' || value >= 1) {
              setSettings({ ...settings, maxRequestsPerWorker: value });
            }
          }}
          onBlur={() => {
            if (settings.maxRequestsPerWorker === '' || settings.maxRequestsPerWorker < 1) {
              setSettings({ ...settings, maxRequestsPerWorker: 1 });
            }
          }}
          error={settings.maxRequestsPerWorker === '' || settings.maxRequestsPerWorker < 1}
          helperText="Maximum number of requests a worker can make in 15 minutes"
          InputProps={{ inputProps: { min: 1 } }}
          fullWidth
        />

        <TextField
          label="Request Interval (seconds)"
          type="number"
          value={settings.requestInterval}
          onChange={(e) => {
            const value = e.target.value === '' ? '' : parseInt(e.target.value);
            if (value === '' || value >= 1) {
              setSettings({ ...settings, requestInterval: value });
            }
          }}
          onBlur={() => {
            if (settings.requestInterval === '' || settings.requestInterval < 1) {
              setSettings({ ...settings, requestInterval: 1 });
            }
          }}
          error={settings.requestInterval === '' || settings.requestInterval < 1}
          helperText="Time to wait between requests"
          InputProps={{ inputProps: { min: 1 } }}
          fullWidth
        />

        <Box sx={{ mt: 2 }}>
          <Button
            variant="contained"
            color="primary"
            onClick={updateSettings}
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </Button>
        </Box>

        <Divider sx={{ my: 3 }} />

        <Typography variant="h6" gutterBottom>
          Worker Status
        </Typography>

        <Grid container spacing={3}>
          <Grid item xs={6}>
            <Paper sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="subtitle1">Active Workers</Typography>
              <Typography variant="h4">
                {status.active_workers} / {status.total_workers}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Currently running / Total available
              </Typography>
            </Paper>
          </Grid>
          <Grid item xs={6}>
            <Paper sx={{ p: 2, textAlign: 'center' }}>
              <Typography variant="subtitle1">Tasks</Typography>
              <Typography variant="h4">
                {status.completed_tasks} / {status.pending_tasks + status.completed_tasks}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Completed / Total
              </Typography>
            </Paper>
          </Grid>
        </Grid>

        <Typography variant="h6" gutterBottom sx={{ mt: 3 }}>
          Worker Utilization
        </Typography>

        <Stack spacing={2}>
          {Object.entries(status.worker_utilization || {}).map(([workerId, data]) => (
            <Paper key={workerId} sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Box>
                  <Typography variant="subtitle1">Worker {workerId}</Typography>
                  <Box sx={{ mt: 1 }}>
                    <Chip
                      label={data.is_active ? 'Active' : 'Inactive'}
                      color={data.is_active ? 'success' : 'default'}
                      size="small"
                      sx={{ mr: 1 }}
                    />
                    <Chip
                      label={data.health_status}
                      color={data.health_status === 'healthy' ? 'success' : 'error'}
                      size="small"
                    />
                  </Box>
                </Box>
                <Box sx={{ textAlign: 'right' }}>
                  <Typography>
                    Tasks: {data.completed_tasks} / {data.assigned_tasks}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Requests (15min): {data.rate_limit_status.requests_15min} / {settings.maxRequestsPerWorker}
                  </Typography>
                </Box>
              </Box>
            </Paper>
          ))}
        </Stack>
      </Stack>
    </Paper>
  );
};

export default WorkerSettings;
