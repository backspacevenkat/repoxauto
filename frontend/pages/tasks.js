import { useState, useEffect } from 'react';
import { useWebSocket } from '../components/WebSocketProvider';
import { useRouter } from 'next/router';
import {
  Box,
  Button,
  Container,
  Grid,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Alert,
  Pagination,
  Stack,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Tabs,
  Tab,
  Link
} from '@mui/material';
import { 
  Upload as UploadIcon, 
  Refresh as RefreshIcon, 
  Visibility as VisibilityIcon, 
  Settings as SettingsIcon,
  TrendingUp as TrendingUpIcon,
  Search as SearchIcon,
  Person as PersonIcon,
  Comment as TweetIcon
} from '@mui/icons-material';
import axios from 'axios';
import TaskDetailsModal from '../components/TaskDetailsModal';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

const formatPST = (dateStr) => {
  if (!dateStr) return '';
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
};

const TaskStatus = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed'
};

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
    case TaskStatus.PENDING:
      return 'warning';
    case TaskStatus.RUNNING:
      return 'info';
    case TaskStatus.COMPLETED:
      return 'success';
    case TaskStatus.FAILED:
      return 'error';
    default:
      return 'default';
  }
};

export default function TasksPage() {
  const router = useRouter();
  const [tasks, setTasks] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [filters, setFilters] = useState({
    status: '',
    type: ''
  });
  const [csvFile, setCsvFile] = useState(null);
  const [uploadType, setUploadType] = useState(TaskType.SCRAPE_PROFILE);
  const [tweetParams, setTweetParams] = useState({
    count: 15,
    hours: 24,
    max_replies: 7
  });
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState({
    maxWorkers: 6,
    requestsPerWorker: 900,
    requestInterval: 15
  });
  const [selectedTab, setSelectedTab] = useState(0);

  const { socket, isConnected } = useWebSocket();

  useEffect(() => {
    // Initial fetch
    fetchTasks();
    fetchStats();
    fetchSettings();

    // Set up WebSocket message handler
    if (socket) {
      const handleMessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'task_update') {
            fetchTasks();
            fetchStats();
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };

      socket.addEventListener('message', handleMessage);
      return () => socket.removeEventListener('message', handleMessage);
    }
  }, [page, filters, socket, isConnected]);

  const fetchSettings = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/settings`);
      setSettings(response.data);
    } catch (err) {
      console.error('Failed to fetch settings:', err);
    }
  };

  const fetchTasks = async () => {
    try {
      setLoading(true);
      const params = {
        page,
        page_size: 50,
        ...(filters.status && { status: filters.status }),
        ...(filters.type && { type: filters.type })
      };
      const response = await axios.get(`${API_BASE_URL}/tasks/list`, { params });
      
      // Group tasks by type
      const groupedTasks = response.data.tasks.reduce((acc, task) => {
        if (!acc[task.type]) {
          acc[task.type] = [];
        }
        acc[task.type].push(task);
        return acc;
      }, {});
      
      setTasks(groupedTasks);
      setTotalPages(response.data.total_pages);
    } catch (err) {
      setError(err.response?.data?.detail?.msg || err.response?.data?.detail || 'Failed to fetch tasks');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/tasks/stats`);
      setStats(response.data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  };

  const handleFileUpload = async (event) => {
    event.preventDefault();
    if (!csvFile) {
      setError('Please select a CSV file');
      return;
    }

    const formData = new FormData();
    formData.append('file', csvFile);

    try {
      setLoading(true);
      const response = await axios.post(`${API_BASE_URL}/tasks/upload`, formData, {
        params: {
          task_type: uploadType,
          count: tweetParams.count,
          hours: tweetParams.hours,
          max_replies: tweetParams.max_replies
        },
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });
      setError(null);
      fetchTasks();
      fetchStats();
    } catch (err) {
      setError(err.response?.data?.detail?.msg || err.response?.data?.detail || 'Failed to upload CSV');
    } finally {
      setLoading(false);
      setCsvFile(null);
    }
  };

  const handleViewTask = (taskId) => {
    setSelectedTaskId(taskId);
    setModalOpen(true);
  };

  const handleSaveSettings = async () => {
    try {
      await axios.post(`${API_BASE_URL}/settings`, settings);
      setSettingsOpen(false);
      fetchStats();
    } catch (err) {
      setError(err.response?.data?.detail?.msg || err.response?.data?.detail || 'Failed to save settings');
    }
  };

  const renderTaskTable = (taskType, taskList) => {
    const isSearchTask = taskType.startsWith('search_');
    const isTrendingTask = taskType === TaskType.SEARCH_TRENDING;

    return (
      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              {!isTrendingTask && <TableCell>Query</TableCell>}
              <TableCell>Status</TableCell>
              <TableCell>Worker Account</TableCell>
              <TableCell>Results</TableCell>
              <TableCell>Created (PST)</TableCell>
              <TableCell>Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {taskList.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} align="center">
                  No tasks found
                </TableCell>
              </TableRow>
            ) : (
              taskList.map((task) => (
                <TableRow key={task.id}>
                  <TableCell>{task.id}</TableCell>
                  {!isTrendingTask && (
                    <TableCell>
                      {isSearchTask ? (
                        <Typography>
                          {task.input_params.keyword}
                        </Typography>
                      ) : (
                        <Link
                          href={`https://twitter.com/${task.input_params.username}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          sx={{ 
                            display: 'flex',
                            alignItems: 'center',
                            gap: 0.5,
                            color: 'primary.main',
                            '&:hover': {
                              textDecoration: 'underline'
                            }
                          }}
                        >
                          @{task.input_params.username}
                          <span style={{ fontSize: '0.8em' }}>↗️</span>
                        </Link>
                      )}
                    </TableCell>
                  )}
                  <TableCell>
                    <Chip
                      label={task.status}
                      color={getStatusColor(task.status)}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    {task.worker_account ? (
                      <Box>
                        <Typography variant="body2">
                          Account: {task.worker_account.account_no}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block">
                          Success Rate: {task.worker_account.success_rate?.toFixed(1)}%
                        </Typography>
                        <Typography variant="caption" color="text.secondary" display="block">
                          Tasks: {task.worker_account.total_tasks || 0}
                        </Typography>
                      </Box>
                    ) : '-'}
                  </TableCell>
                  <TableCell>
                    {task.status === 'completed' && (
                      <Typography variant="body2">
                        {task.result?.trends?.length || 
                         task.result?.tweets?.length || 
                         task.result?.users?.length || 0} results
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>{formatPST(task.created_at)}</TableCell>
                  <TableCell>
                    <Button
                      size="small"
                      startIcon={<VisibilityIcon />}
                      onClick={() => handleViewTask(task.id)}
                    >
                      View Details
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    );
  };

  return (
    <Container maxWidth="xl" sx={{ mt: 4, mb: 4 }}>
      <Grid container spacing={3}>
        {/* Stats */}
        {stats && (
          <Grid item xs={12}>
            <Paper sx={{ p: 2, display: 'flex', gap: 2, position: 'relative' }}>
              <Box>
                <Typography variant="subtitle2">Total Tasks</Typography>
                <Typography variant="h6">{stats.total_tasks}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2">Success Rate</Typography>
                <Typography variant="h6">{stats.success_rate.toFixed(1)}%</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2">Running</Typography>
                <Typography variant="h6">{stats.running_tasks}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2">Pending</Typography>
                <Typography variant="h6">{stats.pending_tasks}</Typography>
              </Box>
              <Box>
                <Typography variant="subtitle2">Active Workers</Typography>
                <Typography variant="h6">{stats.active_workers}/{stats.total_workers}</Typography>
              </Box>
              <Button
                sx={{ position: 'absolute', right: 16 }}
                startIcon={<SettingsIcon />}
                onClick={() => setSettingsOpen(true)}
              >
                Settings
              </Button>
            </Paper>
          </Grid>
        )}

        {/* Upload Form */}
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <form onSubmit={handleFileUpload}>
              <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap" sx={{ gap: 2 }}>
                <Button
                  variant="contained"
                  component="label"
                >
                  Select CSV File
                  <input
                    type="file"
                    accept=".csv"
                    onChange={(e) => setCsvFile(e.target.files[0])}
                    style={{ display: 'none' }}
                  />
                </Button>
                <Typography sx={{ minWidth: '200px' }}>
                  {csvFile ? csvFile.name : 'No file selected'}
                </Typography>
                <FormControl sx={{ minWidth: 200 }}>
                  <InputLabel>Task Type</InputLabel>
                  <Select
                    value={uploadType}
                    label="Task Type"
                    onChange={(e) => setUploadType(e.target.value)}
                  >
                    <MenuItem value={TaskType.SCRAPE_PROFILE}>Scrape Profiles</MenuItem>
                    <MenuItem value={TaskType.SCRAPE_TWEETS}>Scrape Tweets</MenuItem>
                  </Select>
                </FormControl>
                {uploadType === TaskType.SCRAPE_TWEETS && (
                  <Box sx={{ display: 'flex', gap: 2, alignItems: 'center' }}>
                    <FormControl sx={{ width: 120 }}>
                      <TextField
                        label="Tweet Count"
                        type="number"
                        value={tweetParams.count}
                        onChange={(e) => setTweetParams({ ...tweetParams, count: parseInt(e.target.value) })}
                        InputProps={{ 
                          inputProps: { min: 1, max: 100 },
                          size: "small"
                        }}
                        size="small"
                      />
                      <Typography variant="caption" color="textSecondary" sx={{ mt: 0.5 }}>
                        Max 100 tweets
                      </Typography>
                    </FormControl>
                    <FormControl sx={{ width: 120 }}>
                      <TextField
                        label="Hours"
                        type="number"
                        value={tweetParams.hours}
                        onChange={(e) => setTweetParams({ ...tweetParams, hours: parseInt(e.target.value) })}
                        InputProps={{ 
                          inputProps: { min: 1, max: 168 },
                          size: "small"
                        }}
                        size="small"
                      />
                      <Typography variant="caption" color="textSecondary" sx={{ mt: 0.5 }}>
                        Last X hours
                      </Typography>
                    </FormControl>
                    <FormControl sx={{ width: 120 }}>
                      <TextField
                        label="Max Replies"
                        type="number"
                        value={tweetParams.max_replies}
                        onChange={(e) => setTweetParams({ ...tweetParams, max_replies: parseInt(e.target.value) })}
                        InputProps={{ 
                          inputProps: { min: 0, max: 20 },
                          size: "small"
                        }}
                        size="small"
                      />
                      <Typography variant="caption" color="textSecondary" sx={{ mt: 0.5 }}>
                        Replies per tweet (0-20)
                      </Typography>
                    </FormControl>
                  </Box>
                )}
                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  disabled={!csvFile || loading}
                >
                  Upload and Create Tasks
                </Button>
              </Stack>
            </form>
          </Paper>
        </Grid>

        {/* Filters */}
        <Grid item xs={12}>
          <Paper sx={{ p: 2 }}>
            <Stack direction="row" spacing={2} alignItems="center">
              <FormControl sx={{ minWidth: 200 }}>
                <InputLabel>Status</InputLabel>
                <Select
                  value={filters.status}
                  label="Status"
                  onChange={(e) => setFilters({ ...filters, status: e.target.value })}
                >
                  <MenuItem value="">All</MenuItem>
                  {Object.values(TaskStatus).map((status) => (
                    <MenuItem key={status} value={status}>
                      {status.charAt(0).toUpperCase() + status.slice(1)}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button
                startIcon={<RefreshIcon />}
                onClick={fetchTasks}
                disabled={loading}
              >
                Refresh
              </Button>
            </Stack>
          </Paper>
        </Grid>

        {/* Tasks */}
        <Grid item xs={12}>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          
          {loading ? (
            <Box display="flex" justifyContent="center" p={3}>
              <CircularProgress />
            </Box>
          ) : (
            <Box sx={{ width: '100%' }}>
              <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
                <Tabs 
                  value={selectedTab} 
                  onChange={(e, newValue) => setSelectedTab(newValue)}
                  variant="scrollable"
                  scrollButtons="auto"
                >
                  {/* Scraping Tasks */}
                  <Tab 
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {TaskTypeIcons[TaskType.SCRAPE_PROFILE]}
                        Profile Scraping
                        <Chip 
                          label={(tasks[TaskType.SCRAPE_PROFILE] || []).length} 
                          size="small" 
                          color={selectedTab === 0 ? "primary" : "default"}
                        />
                      </Box>
                    } 
                  />
                  <Tab 
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {TaskTypeIcons[TaskType.SCRAPE_TWEETS]}
                        Tweet Scraping
                        <Chip 
                          label={(tasks[TaskType.SCRAPE_TWEETS] || []).length} 
                          size="small"
                          color={selectedTab === 1 ? "primary" : "default"}
                        />
                      </Box>
                    } 
                  />
                  {/* Search Tasks */}
                  <Tab 
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {TaskTypeIcons[TaskType.SEARCH_TRENDING]}
                        Trending Topics
                        <Chip 
                          label={(tasks[TaskType.SEARCH_TRENDING] || []).length} 
                          size="small"
                          color={selectedTab === 2 ? "primary" : "default"}
                        />
                      </Box>
                    } 
                  />
                  <Tab 
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {TaskTypeIcons[TaskType.SEARCH_TWEETS]}
                        Tweet Search
                        <Chip 
                          label={(tasks[TaskType.SEARCH_TWEETS] || []).length} 
                          size="small"
                          color={selectedTab === 3 ? "primary" : "default"}
                        />
                      </Box>
                    } 
                  />
                  <Tab 
                    label={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        {TaskTypeIcons[TaskType.SEARCH_USERS]}
                        User Search
                        <Chip 
                          label={(tasks[TaskType.SEARCH_USERS] || []).length} 
                          size="small"
                          color={selectedTab === 4 ? "primary" : "default"}
                        />
                      </Box>
                    } 
                  />
                </Tabs>
              </Box>
              
              {/* Task Tables */}
              <Box sx={{ position: 'relative', mt: 2 }}>
                {loading && (
                  <Box sx={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, bgcolor: 'rgba(255,255,255,0.7)', zIndex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <CircularProgress />
                  </Box>
                )}
                
                {/* Scraping Tasks */}
                {selectedTab === 0 && renderTaskTable(TaskType.SCRAPE_PROFILE, tasks[TaskType.SCRAPE_PROFILE] || [])}
                {selectedTab === 1 && renderTaskTable(TaskType.SCRAPE_TWEETS, tasks[TaskType.SCRAPE_TWEETS] || [])}
                
                {/* Search Tasks */}
                {selectedTab === 2 && renderTaskTable(TaskType.SEARCH_TRENDING, tasks[TaskType.SEARCH_TRENDING] || [])}
                {selectedTab === 3 && renderTaskTable(TaskType.SEARCH_TWEETS, tasks[TaskType.SEARCH_TWEETS] || [])}
                {selectedTab === 4 && renderTaskTable(TaskType.SEARCH_USERS, tasks[TaskType.SEARCH_USERS] || [])}
              </Box>
            </Box>
          )}
          
          {totalPages > 1 && (
            <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center' }}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={(e, value) => setPage(value)}
                color="primary"
              />
            </Box>
          )}
        </Grid>
      </Grid>

      {/* Task Details Modal */}
      <TaskDetailsModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setSelectedTaskId(null);
        }}
        taskId={selectedTaskId}
      />

      {/* Settings Dialog */}
      <Dialog open={settingsOpen} onClose={() => setSettingsOpen(false)}>
        <DialogTitle>Task Queue Settings</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 2 }}>
            <TextField
              label="Max Workers"
              type="number"
              value={settings.maxWorkers}
              onChange={(e) => {
                const value = e.target.value === '' ? '' : parseInt(e.target.value);
                if (value === '' || (value >= 1 && value <= 12)) {
                  setSettings({ ...settings, maxWorkers: value });
                }
              }}
              onBlur={() => {
                if (settings.maxWorkers === '' || settings.maxWorkers < 1) {
                  setSettings({ ...settings, maxWorkers: 1 });
                } else if (settings.maxWorkers > 12) {
                  setSettings({ ...settings, maxWorkers: 12 });
                }
              }}
              error={settings.maxWorkers === '' || settings.maxWorkers < 1 || settings.maxWorkers > 12}
              helperText={
                settings.maxWorkers === '' || settings.maxWorkers < 1 || settings.maxWorkers > 12
                  ? 'Must be between 1 and 12'
                  : 'Number of concurrent worker accounts'
              }
              InputProps={{ 
                inputProps: { min: 1, max: 12 },
                inputMode: 'numeric',
                pattern: '[0-9]*'
              }}
              fullWidth
            />
            <TextField
              label="Requests Per Worker (15min)"
              type="number"
              value={settings.requestsPerWorker}
              onChange={(e) => {
                const value = e.target.value === '' ? '' : parseInt(e.target.value);
                if (value === '' || value >= 1) {
                  setSettings({ ...settings, requestsPerWorker: value });
                }
              }}
              onBlur={() => {
                if (settings.requestsPerWorker === '' || settings.requestsPerWorker < 1) {
                  setSettings({ ...settings, requestsPerWorker: 1 });
                }
              }}
              error={settings.requestsPerWorker === '' || settings.requestsPerWorker < 1}
              helperText={
                settings.requestsPerWorker === '' || settings.requestsPerWorker < 1
                  ? 'Must be at least 1'
                  : 'Maximum requests per worker in 15 minutes'
              }
              InputProps={{ 
                inputProps: { min: 1 },
                inputMode: 'numeric',
                pattern: '[0-9]*'
              }}
              fullWidth
            />
            <TextField
              label="Request Interval (minutes)"
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
              helperText={
                settings.requestInterval === '' || settings.requestInterval < 1
                  ? 'Must be at least 1'
                  : 'Time between requests in minutes'
              }
              InputProps={{ 
                inputProps: { min: 1 },
                inputMode: 'numeric',
                pattern: '[0-9]*'
              }}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSettingsOpen(false)}>Cancel</Button>
          <Button 
            onClick={handleSaveSettings} 
            variant="contained"
            disabled={
              settings.maxWorkers === '' || 
              settings.maxWorkers < 1 || 
              settings.maxWorkers > 12 ||
              settings.requestsPerWorker === '' ||
              settings.requestsPerWorker < 1 ||
              settings.requestInterval === '' ||
              settings.requestInterval < 1
            }
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}
