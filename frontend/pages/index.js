import React, { useState, useEffect } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Stack,
  Link as MuiLink
} from '@mui/material';
import {
  People as PeopleIcon,
  Task as TaskIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Search as SearchIcon,
  TrendingUp as TrendingUpIcon,
  Person as PersonIcon,
  Comment as TweetIcon
} from '@mui/icons-material';
import Link from 'next/link';
import axios from 'axios';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

const TaskType = {
  SCRAPE_PROFILE: 'scrape_profile',
  SCRAPE_TWEETS: 'scrape_tweets',
  SEARCH_TRENDING: 'search_trending',
  SEARCH_TWEETS: 'search_tweets',
  SEARCH_USERS: 'search_users'
};

const TaskTypeLabels = {
  [TaskType.SCRAPE_PROFILE]: 'Profile Scraping',
  [TaskType.SCRAPE_TWEETS]: 'Tweet Scraping',
  [TaskType.SEARCH_TRENDING]: 'Trending Topics',
  [TaskType.SEARCH_TWEETS]: 'Tweet Search',
  [TaskType.SEARCH_USERS]: 'User Search'
};

const TaskTypeIcons = {
  [TaskType.SCRAPE_PROFILE]: <PersonIcon />,
  [TaskType.SCRAPE_TWEETS]: <TweetIcon />,
  [TaskType.SEARCH_TRENDING]: <TrendingUpIcon />,
  [TaskType.SEARCH_TWEETS]: <SearchIcon />,
  [TaskType.SEARCH_USERS]: <PersonIcon />
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
    default:
      return 'default';
  }
};

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [recentTasks, setRecentTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [statsResponse, tasksResponse] = await Promise.all([
          axios.get(`${API_BASE_URL}/tasks/stats`, {
            headers: {
              'Accept': 'application/json',
              'Content-Type': 'application/json'
            }
          }),
          axios.get(`${API_BASE_URL}/tasks/list?page=1&page_size=5`, {
            headers: {
              'Accept': 'application/json',
              'Content-Type': 'application/json'
            }
          })
        ]);

        // Check if responses are valid
        if (!statsResponse.data) {
          throw new Error('Invalid stats response');
        }

        if (!tasksResponse.data || !Array.isArray(tasksResponse.data.tasks)) {
          throw new Error('Invalid tasks response');
        }

        setStats(statsResponse.data);
        setRecentTasks(tasksResponse.data.tasks);
        setError(null);
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
        const errorMessage = err.response?.data?.detail || err.message || 'Failed to load dashboard data';
        setError(errorMessage);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const formatDateTime = (dateStr) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleString();
  };

  if (loading) {
    return (
      <Container maxWidth="xl">
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
          <CircularProgress />
        </Box>
      </Container>
    );
  }

  if (error) {
    return (
      <Container maxWidth="xl">
        <Paper sx={{ p: 3, mt: 3, bgcolor: 'error.light', color: 'error.contrastText' }}>
          <Typography>{error}</Typography>
        </Paper>
      </Container>
    );
  }

  return (
    <Container maxWidth="xl">
      <Typography variant="h5" gutterBottom sx={{ mb: 3 }}>
        Dashboard
      </Typography>

      <Grid container spacing={3}>
        {/* Stats Cards */}
        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <TaskIcon sx={{ mr: 1, color: 'primary.main' }} />
                <Typography variant="h6">Total Tasks</Typography>
              </Box>
              <Typography variant="h4">{stats?.total_tasks || 0}</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <CheckCircleIcon sx={{ mr: 1, color: 'success.main' }} />
                <Typography variant="h6">Success Rate</Typography>
              </Box>
              <Typography variant="h4">{stats?.success_rate?.toFixed(1) || 0}%</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <TaskIcon sx={{ mr: 1, color: 'warning.main' }} />
                <Typography variant="h6">Running Tasks</Typography>
              </Box>
              <Typography variant="h4">{stats?.running_tasks || 0}</Typography>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} sm={6} md={3}>
          <Card sx={{ height: '100%' }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                <PeopleIcon sx={{ mr: 1, color: 'info.main' }} />
                <Typography variant="h6">Active Workers</Typography>
              </Box>
              <Typography variant="h4">
                {stats?.active_workers || 0}/{stats?.total_workers || 0}
              </Typography>
            </CardContent>
          </Card>
        </Grid>

        {/* Recent Tasks */}
        <Grid item xs={12}>
          <Paper sx={{ p: 3, borderRadius: 2 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
              <Typography variant="h6">
                Recent Tasks
              </Typography>
              <Link href="/tasks" passHref>
                <MuiLink 
                  sx={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: 0.5,
                    textDecoration: 'none',
                    '&:hover': { textDecoration: 'underline' }
                  }}
                >
                  View All Tasks
                  <TaskIcon fontSize="small" />
                </MuiLink>
              </Link>
            </Stack>
            
            {recentTasks.length === 0 ? (
              <Typography color="text.secondary">
                No recent tasks
              </Typography>
            ) : (
              <Stack spacing={2}>
                {recentTasks.map((task) => (
                  <Paper 
                    key={task.id} 
                    variant="outlined" 
                    sx={{ 
                      p: 2,
                      '&:hover': { bgcolor: 'action.hover' }
                    }}
                  >
                    <Stack direction="row" alignItems="center" spacing={2}>
                      <Box sx={{ color: 'action.active' }}>
                        {TaskTypeIcons[task.type]}
                      </Box>
                      <Box sx={{ flex: 1 }}>
                        <Stack direction="row" alignItems="center" spacing={1}>
                          <Typography variant="subtitle1">
                            {TaskTypeLabels[task.type]}
                          </Typography>
                          <Chip
                            label={task.status}
                            size="small"
                            color={getStatusColor(task.status)}
                          />
                        </Stack>
                        <Typography variant="body2" color="text.secondary">
                          {task.type.startsWith('search_') ? (
                            task.type === TaskType.SEARCH_TRENDING ? 
                              'Trending Topics Search' :
                              `Search: "${task.input_params.keyword}"`
                          ) : (
                            `Username: @${task.input_params.username}`
                          )}
                        </Typography>
                      </Box>
                      <Typography variant="body2" color="text.secondary">
                        {formatDateTime(task.created_at)}
                      </Typography>
                    </Stack>
                  </Paper>
                ))}
              </Stack>
            )}
          </Paper>
        </Grid>
      </Grid>
    </Container>
  );
}
