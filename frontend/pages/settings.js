import React from 'react';
import { Container, Typography } from '@mui/material';
import WorkerSettings from '../components/WorkerSettings';

export default function SettingsPage() {
  return (
    <Container maxWidth="xl">
      <Typography variant="h5" gutterBottom sx={{ mb: 3 }}>
        Task Queue Settings
      </Typography>
      <WorkerSettings />
    </Container>
  );
}
