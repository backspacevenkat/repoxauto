import { useState, useEffect, useMemo } from 'react';
import { useWebSocket } from './WebSocketProvider';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Typography,
  Box,
  Chip,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  CircularProgress,
  Alert,
  Link,
  Divider,
  Stack
} from '@mui/material';
import { TrendingUp as TrendingUpIcon } from '@mui/icons-material';
import axios from 'axios';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';

const formatDateTime = (dateStr) => {
  if (!dateStr) return '';
  
  // Use UTC time if available
  if (dateStr.includes('T')) {
    // Parse ISO format (UTC)
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hour12: true,
      timeZoneName: 'short'
    });
  }
  
  // Parse Twitter's format with timezone
  try {
    // Twitter format: "Wed Dec 13 11:59:00 +0000 2023"
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: 'numeric',
      minute: 'numeric',
      second: 'numeric',
      hour12: true,
      timeZoneName: 'short'
    });
  } catch (e) {
    console.error('Error parsing date:', e);
    return dateStr;
  }
};

const formatNumber = (num) => {
  if (num === undefined || num === null) return '0';
  return num.toLocaleString();
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

export default function TaskDetailsModal({ open, onClose, taskId }) {
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [refreshInterval, setRefreshInterval] = useState(null);

  const fetchTask = async () => {
    try {
      setLoading(true);
      const response = await axios.get(`${API_BASE_URL}/tasks/${taskId}`);
      setTask(response.data);
      setError(null);

      // Stop refreshing if task is completed or failed
      if (response.data.status === 'completed' || response.data.status === 'failed') {
        clearInterval(refreshInterval);
        setRefreshInterval(null);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch task details');
    } finally {
      setLoading(false);
    }
  };

  const { socket, isConnected } = useWebSocket();

  useEffect(() => {
    if (open && taskId) {
      fetchTask();

      // Set up WebSocket message handler
      if (socket) {
        const handleMessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'task_update' && data.task_id === taskId) {
              fetchTask();
            }
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };

        socket.addEventListener('message', handleMessage);
        return () => socket.removeEventListener('message', handleMessage);
      }
    }
  }, [open, taskId, socket, isConnected]);

  const renderProfileResult = (result) => (
    <Box>
      <Typography variant="subtitle2" gutterBottom>Profile Data:</Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableBody>
            <TableRow>
              <TableCell component="th">Username</TableCell>
              <TableCell>
                <Link 
                  href={`https://twitter.com/${result.username}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{ 
                    display: 'flex',
                    alignItems: 'center',
                    gap: 0.5,
                    color: 'primary.main',
                    fontWeight: 'medium',
                    '&:hover': {
                      textDecoration: 'underline',
                      color: 'primary.dark'
                    }
                  }}
                >
                  @{result.username}
                  <span style={{ fontSize: '0.8em', marginLeft: '2px' }}>↗️</span>
                </Link>
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Name</TableCell>
              <TableCell>{result.profile_data.name || 'N/A'}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Description</TableCell>
              <TableCell>{result.profile_data.description || 'N/A'}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Location</TableCell>
              <TableCell>{result.profile_data.location || 'N/A'}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">URL</TableCell>
              <TableCell>
                {result.profile_data.url && (
                  <Link 
                    href={result.profile_data.url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    sx={{ 
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 0.5,
                      color: 'primary.main',
                      fontWeight: 'medium',
                      '&:hover': {
                        textDecoration: 'underline',
                        color: 'primary.dark'
                      }
                    }}
                  >
                    {result.profile_data.url}
                    <span style={{ fontSize: '0.8em', marginLeft: '2px' }}>↗️</span>
                  </Link>
                )}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Profile Image</TableCell>
              <TableCell>
                <img 
                  src={result.profile_data.profile_image_url} 
                  alt="Profile" 
                  style={{ maxWidth: 100, borderRadius: '50%' }}
                />
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Banner Image</TableCell>
              <TableCell>
                {result.profile_data.profile_banner_url && (
                  <img 
                    src={result.profile_data.profile_banner_url} 
                    alt="Banner" 
                    style={{ maxWidth: '100%' }}
                  />
                )}
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Metrics</TableCell>
              <TableCell>
                <Typography variant="body2">
                  Followers: {formatNumber(result.profile_data.metrics?.followers_count)}<br/>
                  Following: {formatNumber(result.profile_data.metrics?.following_count)}<br/>
                  Tweets: {formatNumber(result.profile_data.metrics?.tweets_count)}<br/>
                  Likes: {formatNumber(result.profile_data.metrics?.likes_count)}<br/>
                  Media: {formatNumber(result.profile_data.metrics?.media_count)}
                </Typography>
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Created At</TableCell>
              <TableCell>{formatDateTime(result.profile_data.created_at)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell component="th">Verified</TableCell>
              <TableCell>{result.profile_data.verified ? 'Yes' : 'No'}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );

  const renderTweet = (tweet, isReply = false, isThread = false, isThreadStart = false, isLastInThread = false) => (
    <Box sx={{ 
      p: 2,
      position: 'relative',
      ...(isReply && {
        ml: 4,
        borderLeft: '2px solid',
        borderColor: 'divider',
        '&::before': {
          content: '""',
          position: 'absolute',
          top: 0,
          left: '-6px',
          width: '10px',
          height: '10px',
          borderRadius: '50%',
          backgroundColor: 'divider'
        }
      }),
      ...(isThread && {
        ml: 4,
        borderLeft: '2px solid',
        borderColor: 'primary.main',
        '&::before': {
          content: '""',
          position: 'absolute',
          top: 0,
          left: '-6px',
          width: '10px',
          height: '10px',
          borderRadius: '50%',
          backgroundColor: 'primary.main'
        },
        ...(isLastInThread && {
          '&::after': {
            content: '""',
            position: 'absolute',
            bottom: 0,
            left: '-6px',
            width: '10px',
            height: '10px',
            borderRadius: '50%',
            backgroundColor: 'primary.main'
          }
        })
      })
    }}>
      <Box sx={{ display: 'flex', alignItems: 'flex-start', mb: 1 }}>
        <Box sx={{ flex: 1 }}>
          {/* Author info */}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            <Link 
              href={`https://twitter.com/${tweet.author}`}
              target="_blank"
              rel="noopener noreferrer"
              sx={{ 
                color: 'primary.main',
                fontWeight: isThreadStart ? 'medium' : 'regular',
                '&:hover': { textDecoration: 'underline' }
              }}
            >
              @{tweet.author}
            </Link>
            {tweet.is_reply && !isThread && (
              <Typography component="span" color="text.secondary">
                {' '}replying to{' '}
                <Link 
                  href={`https://twitter.com/${tweet.reply_to}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  sx={{ 
                    color: 'primary.main',
                    '&:hover': { textDecoration: 'underline' }
                  }}
                >
                  @{tweet.reply_to}
                </Link>
              </Typography>
            )}
            {' • '}{formatDateTime(tweet.created_at_utc || tweet.created_at)}
          </Typography>

          {/* Retweet info */}
          {tweet.retweeted_by && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              🔄 Retweeted by{' '}
              <Link 
                href={`https://twitter.com/${tweet.retweeted_by}`} 
                target="_blank"
                rel="noopener noreferrer"
                sx={{ 
                  color: 'primary.main',
                  '&:hover': { textDecoration: 'underline' }
                }}
              >
                @{tweet.retweeted_by}
              </Link>
              {' • '}{formatDateTime(tweet.retweeted_at)}
            </Typography>
          )}

          {/* Tweet text */}
          <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', mb: 2 }}>
            {tweet.text}
          </Typography>

          {/* URLs */}
          {tweet.urls && tweet.urls.length > 0 && (
            <Box sx={{ mb: 2 }}>
              {tweet.urls.map((url, idx) => (
                <Typography key={idx} variant="body2">
                  <Link 
                    href={url.url} 
                    target="_blank"
                    rel="noopener noreferrer"
                    sx={{ 
                      color: 'primary.main',
                      '&:hover': { textDecoration: 'underline' }
                    }}
                  >
                    {url.display_url}
                  </Link>
                </Typography>
              ))}
            </Box>
          )}

          {/* Media */}
          {tweet.media && tweet.media.length > 0 && (
            <Box sx={{ 
              display: 'grid',
              gap: 1,
              gridTemplateColumns: tweet.media.length === 1 ? '1fr' : 'repeat(2, 1fr)',
              mb: 2
            }}>
              {tweet.media.map((media, idx) => (
                <Box key={idx}>
                  {media.type === 'photo' && (
                    <img 
                      src={media.url}
                      alt={media.alt_text || 'Tweet media'}
                      style={{ 
                        width: '100%',
                        borderRadius: '16px',
                        maxHeight: isReply ? '300px' : '400px',
                        objectFit: 'cover'
                      }}
                    />
                  )}
                  {media.type === 'video' && (
                    <video 
                      src={media.video_url}
                      controls
                      style={{ 
                        width: '100%',
                        borderRadius: '16px',
                        maxHeight: isReply ? '300px' : '400px'
                      }}
                    />
                  )}
                </Box>
              ))}
            </Box>
          )}

          {/* Tweet metadata */}
          <Box sx={{ 
            display: 'flex', 
            flexDirection: 'column',
            gap: 1,
            mb: (tweet.quoted_tweet || tweet.replies?.length > 0) ? 2 : 0
          }}>
            {/* Metrics */}
            <Box sx={{ 
              display: 'flex', 
              gap: 3, 
              color: 'text.secondary',
              alignItems: 'center'
            }}>
              <Typography variant="body2">
                {formatDateTime(tweet.created_at_utc || tweet.created_at)}
              </Typography>
              <Typography variant="body2">
                👁️ {formatNumber(tweet.metrics?.view_count)}
              </Typography>
              <Typography variant="body2">
                ❤️ {formatNumber(tweet.metrics?.like_count)}
              </Typography>
              <Typography variant="body2">
                🔄 {formatNumber(tweet.metrics?.retweet_count)}
              </Typography>
              <Typography variant="body2">
                💬 {formatNumber(tweet.metrics?.reply_count)}
              </Typography>
              <Link 
                href={tweet.tweet_url}
                target="_blank"
                rel="noopener noreferrer"
                sx={{ 
                  color: 'primary.main',
                  '&:hover': { textDecoration: 'underline' }
                }}
              >
                View on Twitter
              </Link>
            </Box>

            {/* Thread/Reply indicators */}
            {(isThread || tweet.is_reply) && (
              <Box sx={{ 
                display: 'flex',
                gap: 1,
                alignItems: 'center'
              }}>
                {isThread && (
                  <Chip 
                    size="small"
                    label={isThreadStart ? "Thread Start" : "Thread"}
                    color="primary"
                    variant={isThreadStart ? "filled" : "outlined"}
                  />
                )}
                {tweet.is_reply && !isThread && (
                  <Chip 
                    size="small"
                    label="Reply"
                    color="default"
                    variant="outlined"
                  />
                )}
                {tweet.reply_to && !isThread && (
                  <Typography variant="caption" color="text.secondary">
                    to @{tweet.reply_to}
                  </Typography>
                )}
              </Box>
            )}
          </Box>

          {/* Quoted tweet */}
          {tweet.quoted_tweet && (
            <Paper variant="outlined" sx={{ mt: 2, p: 2, bgcolor: 'action.hover' }}>
              {renderTweet(tweet.quoted_tweet, true)}
            </Paper>
          )}

          {/* Replies */}
          {tweet.replies && tweet.replies.length > 0 && (
            <Box sx={{ mt: 2 }}>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Replies ({tweet.replies.length})
              </Typography>
              {tweet.replies.map((reply, idx) => (
                <Box key={idx}>
                  {reply.type === 'thread' ? (
                    // Thread replies
                    <Box>
                      <Typography variant="body2" color="primary" sx={{ mb: 1, fontWeight: 'medium' }}>
                        Thread by @{reply.tweets[0].author} ({reply.tweets.length} tweets)
                      </Typography>
                      {reply.tweets.map((threadTweet, threadIdx) => (
                        <Box key={threadIdx}>
                          {renderTweet(
                            threadTweet, 
                            false, 
                            true, 
                            threadIdx === 0,
                            threadIdx === reply.tweets.length - 1
                          )}
                          {/* Add spacing between thread tweets */}
                          {threadIdx < reply.tweets.length - 1 && (
                            <Box sx={{ height: '16px' }} />
                          )}
                        </Box>
                      ))}
                    </Box>
                  ) : (
                    // Single reply
                    <Box>
                      {renderTweet(reply.tweet, true)}
                    </Box>
                  )}
                  {/* Add spacing between replies */}
                  {idx < tweet.replies.length - 1 && (
                    <Divider sx={{ my: 2 }} />
                  )}
                </Box>
              ))}
            </Box>
          )}
        </Box>
      </Box>
    </Box>
  );

  const renderTweetsResult = (result) => (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        <Link 
          href={`https://twitter.com/${result.username}`} 
          target="_blank" 
          rel="noopener noreferrer"
          sx={{ 
            display: 'flex',
            alignItems: 'center',
            gap: 0.5,
            color: 'primary.main',
            fontWeight: 'medium',
            '&:hover': {
              textDecoration: 'underline',
              color: 'primary.dark'
            }
          }}
        >
          Tweets from @{result.username}
          <span style={{ fontSize: '0.8em', marginLeft: '2px' }}>↗️</span>
        </Link>
        ({result?.tweets?.length || 0} tweets)
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {(result?.tweets || []).map((tweet, index) => (
          <Paper key={index} variant="outlined">
            {renderTweet(tweet)}
          </Paper>
        ))}
      </Box>
    </Box>
  );

  return (
    <Dialog 
      open={open} 
      onClose={onClose}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>
        Task Details
        {task && (
          <Chip
            label={task.status}
            color={getStatusColor(task.status)}
            size="small"
            sx={{ ml: 1 }}
          />
        )}
      </DialogTitle>
      <DialogContent>
        {loading && !task ? (
          <Box display="flex" justifyContent="center" p={3}>
            <CircularProgress />
          </Box>
        ) : error ? (
          <Alert severity="error">{error}</Alert>
        ) : task ? (
          <Box>
            <Typography variant="subtitle2" gutterBottom>Task Information:</Typography>
            <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
              <Table size="small">
                <TableBody>
                  <TableRow>
                    <TableCell component="th">ID</TableCell>
                    <TableCell>{task.id}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell component="th">Type</TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Typography>
                          {task.type.split('_').map(word => 
                            word.charAt(0).toUpperCase() + word.slice(1)
                          ).join(' ')}
                        </Typography>
                        {(task.type === 'reply_tweet' || task.type === 'quote_tweet') && (
                          <Chip
                            label={task.input_params?.meta_data?.api_method || 'graphql'}
                            size="small"
                            variant="outlined"
                            color={task.input_params?.meta_data?.api_method === 'rest' ? 'secondary' : 'primary'}
                          />
                        )}
                      </Stack>
                    </TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell component="th">Worker Account</TableCell>
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
                  </TableRow>
                  <TableRow>
                    <TableCell component="th">Created</TableCell>
                    <TableCell>{formatDateTime(task.created_at)}</TableCell>
                  </TableRow>
                  {task.started_at && (
                    <TableRow>
                      <TableCell component="th">Started</TableCell>
                      <TableCell>{formatDateTime(task.started_at)}</TableCell>
                    </TableRow>
                  )}
                  {task.completed_at && (
                    <TableRow>
                      <TableCell component="th">Completed</TableCell>
                      <TableCell>{formatDateTime(task.completed_at)}</TableCell>
                    </TableRow>
                  )}
                  {task.error && (
                    <TableRow>
                      <TableCell component="th">Error</TableCell>
                      <TableCell>
                        <Alert severity="error" sx={{ mt: 1 }}>
                          {task.error}
                        </Alert>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </TableContainer>

            {task?.status === 'completed' && task?.result && (
              <Box mt={2}>
                {task.type === 'search_trending' ? (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Trending Topics ({((task.result?.data?.trends || task.result?.trends || []).filter(Boolean)).length})
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {(task.result?.data?.trends || task.result?.trends || []).map((trend, index) => (
                        <Paper key={index} variant="outlined" sx={{ p: 2 }}>
                          <Stack direction="row" spacing={2} alignItems="center">
                            <TrendingUpIcon color="action" />
                            <Box sx={{ flex: 1 }}>
                              <Typography variant="subtitle1">{trend.name}</Typography>
                              <Stack direction="row" spacing={2}>
                                {trend.tweet_volume && (
                                  <Typography variant="body2" color="text.secondary">
                                    {trend.tweet_volume.toLocaleString()} tweets
                                  </Typography>
                                )}
                                {trend.domain && (
                                  <Typography variant="body2" color="text.secondary">
                                    Domain: {trend.domain}
                                  </Typography>
                                )}
                              </Stack>
                            </Box>
                          </Stack>
                        </Paper>
                      ))}
                    </Box>
                  </Box>
                ) : task.type === 'search_tweets' ? (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      Tweet Search Results for "{task.input_params?.keyword ?? ''}"
                      ({task.result?.tweets?.length ?? 0} tweets)
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {(task.result?.tweets ?? []).map((tweet, index) => (
                        <Paper key={index} variant="outlined">
                          {renderTweet(tweet)}
                        </Paper>
                      ))}
                    </Box>
                  </Box>
                ) : task.type === 'search_users' ? (
                  <Box>
                    <Typography variant="subtitle2" gutterBottom>
                      User Search Results for "{task.input_params?.keyword ?? ''}"
                      ({task.result?.users?.length ?? 0} users)
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      {(task.result?.users ?? []).map((user, index) => (
                        <Paper key={index} variant="outlined" sx={{ p: 2 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                            {user.profile_image_url && (
                              <img
                                src={user.profile_image_url}
                                alt={user.name}
                                style={{ width: 48, height: 48, borderRadius: '50%' }}
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
                                  {formatNumber(user.metrics?.followers_count)} followers
                                </Typography>
                                <Typography variant="body2">
                                  {formatNumber(user.metrics?.following_count)} following
                                </Typography>
                                <Typography variant="body2">
                                  {formatNumber(user.metrics?.tweets_count)} tweets
                                </Typography>
                              </Stack>
                            </Box>
                          </Box>
                        </Paper>
                      ))}
                    </Box>
                  </Box>
                ) : task.type === 'scrape_profile' ? (
                  renderProfileResult(task.result)
                ) : (
                  renderTweetsResult(task.result)
                )}
              </Box>
            )}
          </Box>
        ) : null}
      </DialogContent>
      <DialogActions>
        {task?.status === 'completed' && (
          <Button
            onClick={() => {
              const dataStr = JSON.stringify(task.result, null, 2);
              const dataUri = 'data:application/json;charset=utf-8,'+ encodeURIComponent(dataStr);
              const downloadAnchorNode = document.createElement('a');
              downloadAnchorNode.setAttribute('href', dataUri);
              downloadAnchorNode.setAttribute('download', `task_${task.id}_result.json`);
              document.body.appendChild(downloadAnchorNode);
              downloadAnchorNode.click();
              downloadAnchorNode.remove();
            }}
          >
            Download Result
          </Button>
        )}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
