import React, { useState, useEffect } from 'react';
import { useWebSocket } from './WebSocketProvider';
import TaskDetailsModal from './TaskDetailsModal';
import {
    Box,
    Button,
    Select,
    MenuItem,
    TextField,
    Typography,
    Paper,
    CircularProgress,
    Alert,
    Stack,
    Chip,
    Link,
    Container,
    Grid,
    IconButton,
    Tooltip,
    Divider
} from '@mui/material';
import { 
    Refresh as RefreshIcon,
    Search as SearchIcon,
    TrendingUp as TrendingIcon,
    Person as PersonIcon,
    Comment as TweetIcon,
    MoreHoriz as MoreIcon
} from '@mui/icons-material';

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';

const SearchPanel = () => {
    // State management
    const [keyword, setKeyword] = useState('');
    const [searchType, setSearchType] = useState('tweets');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [tasks, setTasks] = useState([]);
    const [selectedTaskId, setSelectedTaskId] = useState(null);
    const [modalOpen, setModalOpen] = useState(false);
    const [results, setResults] = useState([]);
    const [nextCursor, setNextCursor] = useState(null);
    const [taskMessage, setTaskMessage] = useState(null);
    const { socket, isConnected } = useWebSocket();

    // WebSocket effect for real-time updates
    useEffect(() => {
        fetchSearchTasks();

        if (socket) {
            const handleMessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log('WebSocket message received:', {
                        type: data.type,
                        taskId: data.task_id,
                        selectedTaskId,
                        status: data.status
                    });
                    
                    if (data.type === 'task_update') {
                        if (data.task_id === selectedTaskId) {
                            console.log('Processing task update for selected task');
                            handleTaskCompletion(data);
                        }
                        fetchSearchTasks();
                    }
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };

            console.log('WebSocket connection status:', {
                isConnected,
                socketState: socket.readyState
            });

            socket.addEventListener('message', handleMessage);
            return () => socket.removeEventListener('message', handleMessage);
        }
    }, [socket, isConnected, selectedTaskId]);

    // Fetch search tasks
    const fetchSearchTasks = async () => {
        try {
            const response = await fetch(
                `${API_BASE_URL}/tasks/list?type=search_trending,search_tweets,search_users&page_size=20`, {
                headers: {
                    'Accept': 'application/json',
                    'Content-Type': 'application/json'
                }
            });
            if (!response.ok) {
                throw new Error(`Failed to fetch tasks: ${response.statusText}`);
            }
            const data = await response.json();
            setTasks(data.tasks || []);
        } catch (err) {
            console.error('Error fetching tasks:', err);
            setError('Failed to fetch recent searches');
        }
    };

    // Handle task completion
    const handleTaskCompletion = (data) => {
        setLoading(false);
        
        // Debug logging
        console.log('Task completion data:', {
            type: data.type,
            status: data.status,
            resultStructure: data.result ? {
                hasData: !!data.result.data,
                hasTrends: !!(data.result.data?.trends || data.result.trends),
                trendsCount: (data.result.data?.trends || data.result.trends || []).length,
                rawResult: data.result
            } : 'No result'
        });

        if (data.status === 'completed' && data.result) {
            // Update results based on search type
            if (data.type === 'search_trending') {
                // Handle nested trends data structure
                const trends = data.result.data?.trends || 
                             data.result.trends || 
                             [];
                
                console.log('Processing trends:', {
                    count: trends.length,
                    sample: trends.slice(0, 3).map(t => ({
                        name: t.name,
                        volume: t.tweet_volume
                    }))
                });
                             
                // Sort trends by tweet volume if available
                const sortedTrends = [...trends].sort((a, b) => {
                    const volumeA = a.tweet_volume || 0;
                    const volumeB = b.tweet_volume || 0;
                    return volumeB - volumeA;
                });
                
                console.log('Sorted trends:', {
                    count: sortedTrends.length,
                    sample: sortedTrends.slice(0, 3).map(t => ({
                        name: t.name,
                        volume: t.tweet_volume
                    }))
                });
                
                setResults(sortedTrends);
                
                // Show completion message
                setTaskMessage({
                    count: sortedTrends.length,
                    type: 'trending topics',
                    timestamp: new Date().toLocaleString()
                });
            } else if (data.type === 'search_tweets') {
                const tweets = data.result.tweets || [];
                if (nextCursor) {
                    setResults(prev => [...prev, ...tweets]);
                } else {
                    setResults(tweets);
                }
                setNextCursor(data.result.next_cursor || null);
                
                // Show completion message
                setTaskMessage({
                    count: tweets.length,
                    type: 'tweets',
                    timestamp: new Date().toLocaleString()
                });
            } else if (data.type === 'search_users') {
                const users = data.result.users || [];
                if (nextCursor) {
                    setResults(prev => [...prev, ...users]);
                } else {
                    setResults(users);
                }
                setNextCursor(data.result.next_cursor || null);
                
                // Show completion message
                setTaskMessage({
                    count: users.length,
                    type: 'users',
                    timestamp: new Date().toLocaleString()
                });
            }
        } else if (data.status === 'failed') {
            setError(`Task failed: ${data.error || 'Unknown error'}`);
            setResults([]);  // Clear results on error
            setTaskMessage(null);  // Clear task message on error
        }
    };

    // Handle search submission
    const handleSearch = async () => {
        try {
            // Reset state
            setLoading(true);
            setError(null);
            setResults([]);
            setNextCursor(null);
            setTaskMessage(null);
            setSelectedTaskId(null);

            // Debug logging for search start
            console.log('Starting search:', {
                type: searchType,
                keyword: keyword || 'N/A'
            });

            let endpoint = '';
            let method = 'GET';
            let body = null;

            // Configure request based on search type
            switch (searchType) {
                case 'trending':
                    endpoint = '/api/search/trending';
                    console.log('Fetching trending topics...');
                    break;
                case 'tweets':
                    endpoint = '/api/search/tweets';
                    method = 'POST';
                    body = { 
                        keyword, 
                        count: 20,
                        save_to_db: true
                    };
                    break;
                case 'users':
                    endpoint = '/api/search/users';
                    method = 'POST';
                    body = { 
                        keyword, 
                        count: 20,
                        save_to_db: true
                    };
                    break;
                default:
                    throw new Error('Invalid search type');
            }

            // Make request
            console.log('Making API request:', {
                endpoint: `${API_BASE_URL}${endpoint}`,
                method,
                hasBody: !!body
            });

            const response = await fetch(`${API_BASE_URL}${endpoint}`, {
                method,
                headers: {
                    'Content-Type': 'application/json',
                },
                body: method === 'POST' ? JSON.stringify(body) : undefined,
            });

            console.log('API response status:', response.status);

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Search failed: ${response.statusText}. ${errorText}`);
            }

            const data = await response.json();
            
            // Validate response
            if (!data) {
                throw new Error('Empty response from server');
            }

            // Set task ID for WebSocket updates
            if (data.task_id) {
                setSelectedTaskId(data.task_id);
                console.log('Task created:', {
                    taskId: data.task_id,
                    type: searchType
                });
                
                // Handle immediate results if available
                if (searchType === 'trending') {
                    // For trending topics, check both data structures
                    const trends = data.data?.trends || data.trends || [];
                    console.log('Immediate trends data:', {
                        count: trends.length,
                        dataStructure: data.data?.trends ? 'nested' : data.trends ? 'flat' : 'none',
                        sample: trends.slice(0, 3).map(t => ({
                            name: t.name,
                            volume: t.tweet_volume
                        }))
                    });
                    
                    // Sort trends by tweet volume
                    const sortedTrends = [...trends].sort((a, b) => {
                        const volumeA = a.tweet_volume || 0;
                        const volumeB = b.tweet_volume || 0;
                        return volumeB - volumeA;
                    });
                    
                    setResults(sortedTrends);
                    setTaskMessage({
                        count: sortedTrends.length,
                        type: 'trending topics',
                        timestamp: new Date().toLocaleString()
                    });
                } else if (searchType === 'tweets' && data.tweets) {
                    setResults(data.tweets);
                    setNextCursor(data.next_cursor || null);
                } else if (searchType === 'users' && data.users) {
                    setResults(data.users);
                    setNextCursor(data.next_cursor || null);
                }
                
                // Fetch updated task list
                await fetchSearchTasks();
            } else {
                throw new Error('No task ID received from server');
            }

        } catch (err) {
            console.error('Search error:', err);
            setError(`Search error: ${err.message}`);
        } finally {
            // Always ensure loading state is cleared
            setLoading(false);
        }
    };

    // Handle load more
    const loadMore = async () => {
        if (!nextCursor || loading) return;

        try {
            setLoading(true);
            
            const response = await fetch(`${API_BASE_URL}/search/${searchType}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    keyword,
                    count: 20,
                    cursor: nextCursor,
                    save_to_db: true
                }),
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Failed to load more: ${response.statusText}. ${errorText}`);
            }

            const data = await response.json();
            if (!data.task_id) {
                throw new Error('No task ID received from server');
            }

            setSelectedTaskId(data.task_id);
            await fetchSearchTasks();

        } catch (err) {
            console.error('Load more error:', err);
            setError(`Load more error: ${err.message}`);
            setLoading(false);
        }
    };

    // Helper functions
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

    const formatDateTime = (dateStr) => {
        if (!dateStr) return '';
        return new Date(dateStr).toLocaleString();
    };

    const getSearchTypeLabel = (type) => {
        switch (type) {
            case 'search_trending':
                return 'Trending Topics';
            case 'search_tweets':
                return 'Tweet Search';
            case 'search_users':
                return 'User Search';
            default:
                return type;
        }
    };

    const getSearchTypeIcon = (type) => {
        switch (type) {
            case 'search_trending':
                return <TrendingIcon />;
            case 'search_tweets':
                return <TweetIcon />;
            case 'search_users':
                return <PersonIcon />;
            default:
                return <SearchIcon />;
        }
    };

    // Render functions for search results
    const renderTrendingTopic = (trend) => {
        if (!trend || !trend.name) return null;

        const tweetCount = trend.tweet_volume ? 
            `${trend.tweet_volume.toLocaleString()} tweets` : 
            'Trending now';
            
        const twitterSearchUrl = `https://twitter.com/search?q=${encodeURIComponent(trend.name)}`;

        return (
            <Paper key={trend.name} variant="outlined" sx={{ p: 2, mb: 2 }}>
                <Stack direction="row" spacing={2} alignItems="center">
                    <TrendingIcon color="primary" />
                    <Box sx={{ flex: 1 }}>
                        <Link
                            href={twitterSearchUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            sx={{
                                color: 'text.primary',
                                textDecoration: 'none',
                                '&:hover': {
                                    textDecoration: 'underline',
                                    color: 'primary.main'
                                }
                            }}
                        >
                            <Typography variant="subtitle1" component="span">
                                #{trend.name}
                            </Typography>
                        </Link>
                        <Stack direction="row" spacing={2} sx={{ mt: 0.5 }}>
                            <Chip
                                label={tweetCount}
                                size="small"
                                variant="outlined"
                                color="primary"
                                sx={{ borderRadius: 1 }}
                            />
                            {trend.domain && (
                                <Chip
                                    label={`Domain: ${trend.domain}`}
                                    size="small"
                                    variant="outlined"
                                    color="secondary"
                                    sx={{ borderRadius: 1 }}
                                />
                            )}
                        </Stack>
                    </Box>
                </Stack>
            </Paper>
        );
    };

    const renderTweet = (tweet) => (
        <Paper key={tweet.id} variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Stack spacing={2}>
                <Stack direction="row" spacing={2} alignItems="center">
                    <Typography variant="subtitle1">@{tweet.author}</Typography>
                    <Typography variant="body2" color="text.secondary">
                        {formatDateTime(tweet.created_at)}
                    </Typography>
                </Stack>
                <Typography variant="body1">{tweet.text}</Typography>
                <Stack direction="row" spacing={3} color="text.secondary">
                    <Typography variant="body2">
                        💬 {tweet?.metrics?.reply_count ?? 0}
                    </Typography>
                    <Typography variant="body2">
                        🔄 {tweet?.metrics?.retweet_count ?? 0}
                    </Typography>
                    <Typography variant="body2">
                        ❤️ {tweet?.metrics?.like_count ?? 0}
                    </Typography>
                    <Typography variant="body2">
                        👁️ {tweet?.metrics?.view_count ?? 0}
                    </Typography>
                </Stack>
                {tweet.media && tweet.media.length > 0 && (
                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        {tweet.media.map((media, index) => (
                            media.type === 'photo' ? (
                                <Box
                                    key={index}
                                    component="img"
                                    src={media.url}
                                    alt={media.alt_text || 'Tweet media'}
                                    sx={{
                                        maxHeight: 200,
                                        maxWidth: '100%',
                                        objectFit: 'cover',
                                        borderRadius: 1
                                    }}
                                />
                            ) : media.type === 'video' && (
                                <Box
                                    key={index}
                                    component="video"
                                    src={media.video_url}
                                    controls
                                    sx={{
                                        maxHeight: 200,
                                        maxWidth: '100%',
                                        borderRadius: 1
                                    }}
                                />
                            )
                        ))}
                    </Box>
                )}
            </Stack>
        </Paper>
    );

    const renderUser = (user) => (
        <Paper key={user.id} variant="outlined" sx={{ p: 2, mb: 2 }}>
            <Stack direction="row" spacing={2}>
                {user.profile_image_url && (
                    <Box
                        component="img"
                        src={user.profile_image_url}
                        alt={user.name}
                        sx={{
                            width: 48,
                            height: 48,
                            borderRadius: '50%'
                        }}
                    />
                )}
                <Box sx={{ flex: 1 }}>
                    <Typography variant="subtitle1">{user.name}</Typography>
                    <Link
                        href={`https://twitter.com/${user.screen_name}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        sx={{ 
                            color: 'primary.main',
                            '&:hover': { textDecoration: 'underline' }
                        }}
                    >
                        @{user.screen_name}
                    </Link>
                    {user.description && (
                        <Typography variant="body2" sx={{ mt: 1 }}>
                            {user.description}
                        </Typography>
                    )}
                    <Stack direction="row" spacing={2} sx={{ mt: 1 }} color="text.secondary">
                        <Typography variant="body2">
                            {(user?.metrics?.followers_count || 0).toLocaleString()} followers
                        </Typography>
                        <Typography variant="body2">
                            {(user?.metrics?.following_count || 0).toLocaleString()} following
                        </Typography>
                        <Typography variant="body2">
                            {(user?.metrics?.tweets_count || 0).toLocaleString()} tweets
                        </Typography>
                    </Stack>
                </Box>
            </Stack>
        </Paper>
    );

    // Render component
    return (
        <Container maxWidth="xl">
            {/* Search Controls */}
            <Paper sx={{ p: 2, mb: 3 }}>
                <Stack direction="row" spacing={2} alignItems="center">
                    <Select
                        value={searchType}
                        onChange={(e) => setSearchType(e.target.value)}
                        disabled={loading}
                        size="small"
                        sx={{ minWidth: 150 }}
                        startAdornment={
                            <Box sx={{ mr: 1, display: 'flex', alignItems: 'center' }}>
                                {searchType === 'trending' ? <TrendingIcon /> :
                                 searchType === 'tweets' ? <TweetIcon /> :
                                 <PersonIcon />}
                            </Box>
                        }
                    >
                        <MenuItem value="trending">
                            <Stack direction="row" spacing={1} alignItems="center">
                                <TrendingIcon />
                                <span>Trending Topics</span>
                            </Stack>
                        </MenuItem>
                        <MenuItem value="tweets">
                            <Stack direction="row" spacing={1} alignItems="center">
                                <TweetIcon />
                                <span>Tweets</span>
                            </Stack>
                        </MenuItem>
                        <MenuItem value="users">
                            <Stack direction="row" spacing={1} alignItems="center">
                                <PersonIcon />
                                <span>Users</span>
                            </Stack>
                        </MenuItem>
                    </Select>
                    
                    {searchType !== 'trending' && (
                        <TextField
                            size="small"
                            value={keyword}
                            onChange={(e) => setKeyword(e.target.value)}
                            placeholder="Enter search keyword..."
                            sx={{ flex: 1 }}
                            disabled={loading}
                            onKeyPress={(e) => {
                                if (e.key === 'Enter' && !loading && keyword) {
                                    handleSearch();
                                }
                            }}
                            InputProps={{
                                startAdornment: (
                                    <SearchIcon sx={{ mr: 1, color: 'action.active' }} />
                                ),
                            }}
                        />
                    )}
                    
                    <Button
                        variant="contained"
                        onClick={handleSearch}
                        disabled={loading || (searchType !== 'trending' && !keyword)}
                        startIcon={loading ? <CircularProgress size={20} /> : <SearchIcon />}
                    >
                        {loading ? 'Searching...' : 'Search'}
                    </Button>
                    
                    <Tooltip title="Refresh search tasks">
                        <IconButton
                            onClick={fetchSearchTasks}
                            disabled={loading}
                            color="primary"
                        >
                            <RefreshIcon />
                        </IconButton>
                    </Tooltip>
                </Stack>
            </Paper>

            {/* Error Display */}
            {error && (
                <Alert 
                    severity="error" 
                    sx={{ mb: 3 }}
                    onClose={() => setError(null)}
                >
                    {error}
                    {!isConnected && (
                        <Typography sx={{ mt: 1 }}>
                            WebSocket is disconnected. Real-time updates may be delayed.
                        </Typography>
                    )}
                </Alert>
            )}

            {/* Task Message */}
            {taskMessage && !loading && (
                <Paper sx={{ p: 2, mb: 3, bgcolor: 'success.light' }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                        <Typography color="success.contrastText">
                            Found {taskMessage.count} {taskMessage.type}
                        </Typography>
                        <Typography variant="body2" color="success.contrastText">
                            Updated at {taskMessage.timestamp}
                        </Typography>
                    </Stack>
                </Paper>
            )}

            {/* Search Results */}
            <Paper sx={{ p: 2, mb: 3 }}>
                <Stack direction="row" spacing={2} alignItems="center" mb={2}>
                    <Typography variant="h6">
                        {searchType === 'trending' ? 'Trending Topics' : 'Search Results'}
                    </Typography>
                    {results.length > 0 && (
                        <Chip
                            label={`${results.length} ${searchType === 'trending' ? 'trends' : searchType}`}
                            size="small"
                            color="primary"
                            variant="outlined"
                        />
                    )}
                </Stack>
                <Box>
                    {results.length > 0 ? (
                        <Box>
                            {results.map((result) => {
                                switch (searchType) {
                                    case 'trending':
                                        return renderTrendingTopic(result);
                                    case 'tweets':
                                        return renderTweet(result);
                                    case 'users':
                                        return renderUser(result);
                                    default:
                                        return null;
                                }
                            })}
                            {nextCursor && (
                                <Button
                                    fullWidth
                                    onClick={loadMore}
                                    disabled={loading}
                                    startIcon={loading ? <CircularProgress size={20} /> : <MoreIcon />}
                                    sx={{ mt: 2 }}
                                >
                                    {loading ? 'Loading more...' : 'Load More'}
                                </Button>
                            )}
                        </Box>
                    ) : (
                        <Paper 
                            variant="outlined" 
                            sx={{ 
                                p: 4, 
                                textAlign: 'center',
                                bgcolor: 'action.hover'
                            }}
                        >
                            <Stack spacing={1} alignItems="center">
                                {searchType === 'trending' ? (
                                    <>
                                        <TrendingIcon sx={{ fontSize: 40, color: 'text.secondary' }} />
                                        <Typography color="text.secondary">
                                            No trending topics available
                                        </Typography>
                                        <Typography variant="body2" color="text.secondary">
                                            Try refreshing in a few moments
                                        </Typography>
                                    </>
                                ) : (
                                    <>
                                        <SearchIcon sx={{ fontSize: 40, color: 'text.secondary' }} />
                                        <Typography color="text.secondary">
                                            No results found
                                        </Typography>
                                        <Typography variant="body2" color="text.secondary">
                                            Try different search terms
                                        </Typography>
                                    </>
                                )}
                            </Stack>
                        </Paper>
                    )}
                </Box>
            </Paper>

            {/* Recent Search Tasks */}
            <Paper sx={{ p: 2 }}>
                <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                    <Typography variant="h6">
                        Recent Searches
                    </Typography>
                    <Chip 
                        label={`${tasks.length} searches`}
                        size="small"
                        color="primary"
                        variant="outlined"
                    />
                </Stack>
                
                <Box sx={{ mt: 2 }}>
                    {tasks.length === 0 ? (
                        <Paper 
                            variant="outlined" 
                            sx={{ 
                                p: 4, 
                                textAlign: 'center',
                                bgcolor: 'action.hover'
                            }}
                        >
                            <Typography color="text.secondary">
                                No recent searches
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                                Search results will appear here
                            </Typography>
                        </Paper>
                    ) : (
                        <Grid container spacing={2}>
                            {tasks.map((task) => (
                                <Grid item xs={12} key={task.id}>
                                    <Paper 
                                        variant="outlined" 
                                        sx={{ 
                                            p: 2,
                                            cursor: 'pointer',
                                            transition: 'all 0.2s',
                                            '&:hover': {
                                                bgcolor: 'action.hover',
                                                transform: 'translateY(-1px)',
                                                boxShadow: 1
                                            }
                                        }}
                                        onClick={() => {
                                            setSelectedTaskId(task.id);
                                            setModalOpen(true);
                                        }}
                                    >
                                        <Stack direction="row" justifyContent="space-between" alignItems="center">
                                            <Stack direction="row" spacing={2} alignItems="center">
                                                {getSearchTypeIcon(task.type)}
                                                <Box>
                                                    <Typography variant="subtitle1">
                                                        {getSearchTypeLabel(task.type)}
                                                        {task.input_params?.keyword && (
                                                            <Typography 
                                                                component="span" 
                                                                sx={{ 
                                                                    ml: 1,
                                                                    color: 'text.secondary',
                                                                    fontStyle: 'italic'
                                                                }}
                                                            >
                                                                "{task.input_params.keyword}"
                                                            </Typography>
                                                        )}
                                                    </Typography>
                                                    <Typography variant="body2" color="text.secondary">
                                                        Created: {formatDateTime(task.created_at)}
                                                    </Typography>
                                                </Box>
                                            </Stack>
                                            <Stack direction="row" spacing={2} alignItems="center">
                                                {task.status === 'completed' && (
                                                    <Chip
                                                        label={`${
                                                            task.type === 'search_trending' 
                                                                ? ((task.result?.data?.trends || task.result?.trends || []).filter(Boolean)).length
                                                                : task.type === 'search_tweets'
                                                                ? ((task.result?.tweets || []).filter(Boolean)).length
                                                                : task.type === 'search_users'
                                                                ? ((task.result?.users || []).filter(Boolean)).length
                                                                : 0
                                                        } results`}
                                                        size="small"
                                                        variant="outlined"
                                                        color={task.type === 'search_trending' ? 'primary' : 'default'}
                                                    />
                                                )}
                                                <Chip
                                                    label={task.status}
                                                    color={getStatusColor(task.status)}
                                                    size="small"
                                                    icon={task.status === 'running' ? 
                                                        <CircularProgress size={12} color="inherit" /> : 
                                                        undefined
                                                    }
                                                />
                                            </Stack>
                                        </Stack>
                                    </Paper>
                                </Grid>
                            ))}
                        </Grid>
                    )}
                </Box>
            </Paper>

            {/* Task Details Modal */}
            <TaskDetailsModal
                open={modalOpen}
                onClose={() => {
                    setModalOpen(false);
                    setSelectedTaskId(null);
                }}
                taskId={selectedTaskId}
            />
        </Container>
    );
};

export default SearchPanel;
