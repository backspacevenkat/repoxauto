import React, { useState, useEffect } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  TextField,
  Typography,
  Switch,
  FormControlLabel,
  Alert
} from '@mui/material';

export default function FollowSettingsPanel() {
  const [settings, setSettings] = useState({
    max_follows_per_interval: 1,
    interval_minutes: 16,
    max_follows_per_day: 30,
    internal_ratio: 5,
    external_ratio: 25,
    min_following: 300,
    max_following: 400,
    schedule_groups: 3,
    schedule_hours: 8,
    is_active: false
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  useEffect(() => {
    fetchSettings();
  }, []);

  const apiUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

  const fetchSettings = async () => {
    try {
      const response = await fetch(`${apiUrl}/follow/settings`, {
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      if (!response.ok) throw new Error('Failed to fetch settings');
      const data = await response.json();
      setSettings(data);
      setError(null);
    } catch (error) {
      console.error('Error fetching settings:', error);
      setError('Failed to load settings');
    }
  };

  const handleChange = (event) => {
    const { name, value, type, checked } = event.target;
    setSettings(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : parseInt(value)
    }));
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(`${apiUrl}/follow/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(settings)
      });
      if (!response.ok) throw new Error('Failed to update settings');
      await fetchSettings();
      setSuccess('Settings updated successfully');
    } catch (error) {
      console.error('Error updating settings:', error);
      setError('Failed to update settings');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h5" gutterBottom>
          Follow System Settings
        </Typography>

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
        
        <Grid container spacing={3}>
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Max Follows Per Interval"
              name="max_follows_per_interval"
              type="number"
              value={settings.max_follows_per_interval}
              onChange={handleChange}
              margin="normal"
              helperText="Maximum follows allowed per interval"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Interval Minutes"
              name="interval_minutes"
              type="number"
              value={settings.interval_minutes}
              onChange={handleChange}
              margin="normal"
              helperText="Minutes between follow actions"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Max Follows Per Day"
              name="max_follows_per_day"
              type="number"
              value={settings.max_follows_per_day}
              onChange={handleChange}
              margin="normal"
              helperText="Maximum follows allowed per day"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Internal Ratio"
              name="internal_ratio"
              type="number"
              value={settings.internal_ratio}
              onChange={handleChange}
              margin="normal"
              helperText="Number of internal accounts to follow per day"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="External Ratio"
              name="external_ratio"
              type="number"
              value={settings.external_ratio}
              onChange={handleChange}
              margin="normal"
              helperText="Number of external accounts to follow per day"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Min Following"
              name="min_following"
              type="number"
              value={settings.min_following}
              onChange={handleChange}
              margin="normal"
              helperText="Minimum following count per account"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Max Following"
              name="max_following"
              type="number"
              value={settings.max_following}
              onChange={handleChange}
              margin="normal"
              helperText="Maximum following count per account"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Schedule Groups"
              name="schedule_groups"
              type="number"
              value={settings.schedule_groups}
              onChange={handleChange}
              margin="normal"
              helperText="Number of groups to divide accounts into"
            />
          </Grid>
          
          <Grid item xs={12} sm={6}>
            <TextField
              fullWidth
              label="Schedule Hours"
              name="schedule_hours"
              type="number"
              value={settings.schedule_hours}
              onChange={handleChange}
              margin="normal"
              helperText="Hours per schedule window"
            />
          </Grid>
        </Grid>

        <Box mt={3}>
          <Button
            variant="contained"
            color="primary"
            onClick={handleSubmit}
            disabled={loading}
          >
            {loading ? 'Saving...' : 'Save Settings'}
          </Button>
        </Box>
      </CardContent>
    </Card>
  );
}
