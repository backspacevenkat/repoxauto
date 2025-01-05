# Twitter Actions System

This system allows bulk processing of Twitter actions (like, retweet, reply, quote, post) while respecting rate limits and handling queuing.

## Action Types

Currently Supported:
- `like`: Like a tweet
- `RT` or `retweet`: Retweet a tweet

Coming Soon:
- `reply`: Reply to a tweet
- `quote`: Quote tweet
- `post`: Create a new tweet

## CSV Format

Actions are processed from a CSV file with the following columns:

```csv
account_no,task_type,source_tweet,text_content,media
act123,like,https://x.com/username/status/123456789,,
act456,RT,https://x.com/username/status/987654321,,
act789,reply,https://x.com/username/status/456789123,This is a reply,image.jpg
```

### Column Descriptions

- `account_no`: Account identifier to perform the action
- `task_type`: Type of action (`like`, `RT`, `reply`, `quote`, `post`)
- `source_tweet`: URL of the tweet to act on (not required for `post` type)
- `text_content`: Text content for replies, quotes, and posts (required for these types)
- `media`: Optional media file path for actions that support media attachments

## Rate Limits

The system enforces the following rate limits per account:

### Like Actions
- 30 per 15 minutes
- 50 per hour
- 500 per day
- 30 seconds minimum interval

### Retweet Actions
- 15 per 15 minutes
- 25 per hour
- 250 per day
- 60 seconds minimum interval

### Reply/Quote/Post Actions (Coming Soon)
- 10 per 15 minutes
- 20 per hour
- 200 per day
- 90 seconds minimum interval

## Usage

1. Create a CSV file following the format above
2. Run the action processor:

```bash
python process_actions.py account_actions.csv
```

With multiple workers:
```bash
python process_actions.py account_actions.csv --workers 3
```

Monitor mode:
```bash
python process_actions.py account_actions.csv --monitor
```

## Action Status

Actions can have the following statuses:

- `pending`: Queued for processing
- `running`: Currently being executed
- `completed`: Successfully completed
- `failed`: Failed to execute
- `cancelled`: Cancelled before execution

## Error Handling

- Failed actions are logged with detailed error messages
- Rate limit errors include reset time information
- Actions can be retried using the retry endpoint
- Stale actions are automatically cleaned up after 1 hour

## Monitoring

The system provides real-time monitoring of:
- Action queue status
- Rate limit status per account
- Success/failure rates
- Error messages and rate limit resets

## Logs

Logs are stored in the `logs` directory:
- `process_actions_YYYYMMDD_HHMMSS.log`: Main process log
- `action_worker.log`: Worker process log

## API Endpoints

### Import Actions
```
POST /actions/import
Content-Type: multipart/form-data
Body: CSV file
```

### List Actions
```
GET /actions/list
Query params:
- skip: Number of items to skip
- limit: Number of items per page
- status: Filter by status
- action_type: Filter by action type
```

### Get Action Status
```
GET /actions/status/{action_id}
```

### Retry Failed Action
```
POST /actions/{action_id}/retry
```

### Cancel Pending Action
```
POST /actions/{action_id}/cancel
```

## Future Actions

When implementing reply, quote, or post actions:

1. Include required text_content in CSV
2. Add media files if needed
3. System will automatically:
   - Validate content requirements
   - Apply appropriate rate limits
   - Handle media uploads
   - Process actions in queue

## Best Practices

1. Start with small batches to test
2. Monitor rate limits using `--monitor` flag
3. Use multiple workers for large batches
4. Include error handling in your workflow
5. Keep media files in a consistent location
6. Regular backup of action status

## Troubleshooting

Common issues and solutions:

1. Rate Limit Errors
   - Check account's current rate limit status
   - Reduce number of workers
   - Increase intervals between actions

2. Authentication Errors
   - Verify account credentials
   - Check if account is locked/restricted

3. Media Upload Errors
   - Verify file paths
   - Check supported formats
   - Ensure files are not too large

4. Queue Processing Issues
   - Check worker logs
   - Verify database connectivity
   - Monitor system resources
