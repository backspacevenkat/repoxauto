# Xauto Active Context

## Current System State

### Core Functionality
1. **Account Management**
   - ✅ Account Import System
     - **CSV Import Requirements**:
       ```csv
       # Required Fields
       account_no: Unique identifier (e.g., WACC001)
       login: Twitter username without @ symbol
       password: Account password
       email: Recovery email address
       email_password: Email account password
       auth_token: Twitter auth token
       ct0: Twitter ct0 token
       
       # Proxy Configuration (if using)
       proxy_url: Proxy server URL
       proxy_port: Proxy port number
       proxy_username: Proxy authentication username
       proxy_password: Proxy authentication password
       
       # Optional Fields
       user_agent: Custom browser user agent
       two_fa: 2FA backup code
       ```
     - **Validation Rules**:
       - File must be UTF-8 encoded CSV
       - Maximum file size: 10MB
       - Required fields cannot be empty
       - Proxy fields must all be present if any is provided
       - Duplicate account_no values are not allowed
     
     - **Import Process**:
       1. Upload CSV file
       2. File format validation
       3. Data validation
       4. Duplicate checking
       5. Account creation/update
       6. Status broadcast via WebSocket
   
   - ✅ Account Validation System
     - **Validation Process**:
       1. Check account credentials
       2. Verify proxy connection
       3. Test Twitter authentication
       4. Handle 2FA if needed
       5. Verify account status
       6. Update database state
       7. Broadcast status via WebSocket
     
     - **Parallel Validation**:
       - Default: 6 concurrent threads
       - Configurable range: 1-12 threads
       - Automatic batch size adjustment
       - Rate limit aware
     
     - **Recovery Procedures**:
       1. Detect account status (suspended/locked)
       2. Attempt email verification
       3. Handle CAPTCHA challenges
       4. Process 2FA if needed
       5. Verify recovery success
     
     - **Status Updates**:
       ```typescript
       interface ValidationUpdate {
         account_no: string;
         status: 'validating' | 'completed' | 'failed' | 'recovering';
         message: string;
         timestamp: string;
         error?: string;
       }
       ```
   
   - ✅ Password Management Service
     - **Password Requirements**:
       ```typescript
       interface PasswordRules {
         minLength: 20;
         required: {
           uppercase: true;    // At least one uppercase letter
           lowercase: true;    // At least one lowercase letter
           numbers: true;      // At least one number
           symbols: true;      // At least one symbol
           timestamp: true;    // Append current date
         };
         prohibited: {
           commonPatterns: true;   // No common password patterns
           accountInfo: true;      // No username/email in password
           repeatingChars: true;   // No character repetition > 2
         };
       }
       ```
     
     - **2FA Integration**:
       - Service URL: https://2fa.fb.rip/
       - Timeout: 15 seconds
       - Auto-retry: 3 attempts
       - Fallback to backup codes
     
     - **Cookie Management**:
       - Auto-refresh every 24 hours
       - Rotation on validation failure
       - Backup of previous valid cookies
       - Real-time status updates
   
   - ✅ Proxy Management
     - Automatic URL encoding
     - Connection validation
     - Port rotation on failure
     - Health checking
   
   - ✅ Account Types
     - Normal accounts: Standard Twitter accounts
     - Worker accounts: Dedicated for scraping operations
     - State management for both types
     - Type-specific validation flows

2. **Task Processing System**
   - ✅ Task Queue Management
     - **Task Priority Levels**:
       ```python
       PRIORITY_LEVELS = {
           'HIGH': 1,    # Account validation/recovery
           'MEDIUM': 2,  # Profile updates, follows
           'LOW': 3,     # Scraping operations
           'BATCH': 4    # Bulk operations
       }
       ```
     
     - **Queue Configuration**:
       ```python
       QUEUE_CONFIG = {
           'redis_url': 'redis://localhost:6379/0',
           'max_retries': 3,
           'retry_delay': 60,  # seconds
           'batch_size': 100,
           'worker_concurrency': 6
       }
       ```
     
     - **Batch Processing Rules**:
       - Maximum 1000 tasks per batch
       - Auto-split into chunks of 100
       - Rate limit aware distribution
       - Progress tracking per chunk
   
   - ✅ Rate Limiting
     - **Twitter API Limits**:
       ```python
       RATE_LIMITS = {
           'profile_scrape': {
               'window': 900,    # 15 minutes
               'max_requests': 900,
               'per_account': 100
           },
           'follow': {
               'daily_limit': 400,
               'hourly_limit': 50,
               'minimum_interval': 60  # seconds
           }
       }
       ```
     
     - **Backoff Strategy**:
       1. Initial delay: 60 seconds
       2. Exponential increase: delay * 2
       3. Maximum delay: 30 minutes
       4. Reset after window expiry
   
   - ✅ Task Monitoring
     - **Status Updates**:
       ```typescript
       interface TaskUpdate {
         task_id: string;
         type: TaskType;
         status: 'pending' | 'running' | 'completed' | 'failed';
         progress: number;
         error?: string;
         result?: any;
         metrics: {
           start_time: string;
           end_time?: string;
           duration?: number;
           retries: number;
         }
       }
       ```
     
     - **Performance Metrics**:
       - Success/failure rates
       - Average completion time
       - Resource utilization
       - Rate limit status
   
   - ✅ Task Types
     - **Profile Updates**:
       ```csv
       # CSV Format
       account_no,name,description,url,location,profile_image,profile_banner,lang
       
       # Field Limits
       name: 50 chars max
       description: 160 chars max
       url: Valid URL
       location: 30 chars max
       profile_image: Direct JPG/PNG URL
       profile_banner: Direct JPG/PNG URL
       lang: ISO language code
       ```
     
     - **Follow Operations**:
       ```csv
       # Internal List Format
       username
       user1
       user2
       
       # External List Format
       username
       target1
       target2
       
       # Validation Rules
       - No @ symbol in usernames
       - One username per line
       - Max 1000 usernames per file
       - UTF-8 encoding required
       ```
     
     - **Scraping Tasks**:
       ```python
       SCRAPE_CONFIG = {
           'profile': {
               'fields': ['bio', 'location', 'website', 'joined_date', 'metrics'],
               'max_retries': 3
           },
           'tweets': {
               'max_count': 100,
               'include_replies': False,
               'include_retweets': False
           }
       }
       ```

3. **Frontend System**
   - ✅ Account Dashboard
     - **Account List Features**:
       ```typescript
       interface AccountFilters {
         search: string;        // Search by account_no, login, email
         status: string[];      // Filter by validation status
         type: 'all' | 'normal' | 'worker';
         sortBy: 'account_no' | 'login' | 'last_validation';
         sortOrder: 'asc' | 'desc';
       }
       ```
     
     - **Bulk Operations**:
       - Select all accounts (current page or all pages)
       - Delete selected accounts (with confirmation)
       - Export selected accounts to CSV
       - Validate selected accounts (parallel processing)
     
     - **CSV Import Instructions**:
       ```markdown
       1. Prepare CSV file with required columns
       2. Ensure UTF-8 encoding
       3. Maximum file size: 10MB
       4. Click "Select CSV File" or drag & drop
       5. Review validation results
       6. Confirm import if no errors
       ```
   
   - ✅ Task Management
     - **Task Creation**:
       ```typescript
       interface TaskOptions {
         type: TaskType;
         priority: 1 | 2 | 3 | 4;  // Priority levels
         worker_account?: string;   // Specific worker or auto-assign
         params: {
           max_items?: number;      // For scraping tasks
           include_replies?: boolean;
           include_retweets?: boolean;
           [key: string]: any;
         }
       }
       ```
     
     - **Progress Monitoring**:
       - Real-time status updates via WebSocket
       - Progress percentage for batch tasks
       - Error details with retry options
       - Result preview with export
   
   - ✅ Real-time Updates
     - **WebSocket Events**:
       ```typescript
       type EventType = 
         | 'account_update'    // Account status changes
         | 'task_update'       // Task progress/completion
         | 'validation_update' // Validation status
         | 'error'            // System errors
         | 'rate_limit'       // Rate limit warnings
       
       interface WebSocketMessage {
         type: EventType;
         data: any;
         timestamp: string;
       }
       ```
     
     - **Connection Management**:
       - Automatic reconnection (exponential backoff)
       - Connection status indicator
       - Offline mode handling
       - Message queue for reconnection
   
   - ✅ Material UI Integration
     - **Theme Configuration**:
       ```typescript
       const theme = {
         palette: {
           primary: { main: '#007bff' },
           secondary: { main: '#6c757d' },
           error: { main: '#dc3545' },
           warning: { main: '#ffc107' },
           success: { main: '#28a745' }
         },
         components: {
           MuiButton: { /* Button styles */ },
           MuiTable: { /* Table styles */ },
           MuiAlert: { /* Alert styles */ }
         }
       }
       ```
     
     - **UI Components**:
       - Data tables with sorting/filtering
       - Progress indicators
       - Status chips
       - Toast notifications
       - Loading skeletons
       - Confirmation dialogs

### Active Components

#### Backend Services
1. **Password Manager Service**
   ```python
   class PasswordManager:
       # Core features
       - Secure password generation with timestamp
       - Browser automation with Playwright
       - Proxy rotation with retries
       - Cookie management
       
       # 2FA handling
       - 2FA service integration
       - Code verification
       - Automatic retry
       
       # Error handling
       - Timeout management
       - Proxy rotation
       - State recovery
       - Validation retries
   ```

2. **Account Management Service**
   ```python
   class AccountRouter:
       # Core operations
       - CRUD operations with validation
       - Bulk import/export
       - Status management
       - Worker assignment
       
       # Validation system
       - Parallel validation
       - Recovery procedures
       - Status tracking
       - Error handling
       
       # WebSocket integration
       - Real-time updates
       - Status broadcasting
       - Error notifications
       - Connection management
   ```

3. **Task Processing System**
   ```python
   class TaskProcessor:
       # Queue management
       - Priority scheduling
       - Rate limit compliance
       - Worker distribution
       - Batch processing
       
       # Task execution
       - Worker assignment
       - Progress tracking
       - Result collection
       - Error handling
       
       # Status management
       - Real-time updates
       - WebSocket broadcasting
       - Metric collection
       - Performance monitoring
   ```

#### Frontend Components
1. **Account Management**
   - Account listing and filtering
   - Status monitoring
   - Bulk operations
   - Real-time updates

2. **Task Management**
   - Task creation
   - Progress monitoring
   - Result viewing
   - Error handling

## Recent Implementations

### Password Management System
```python
# Key features implemented
- Secure password generation
- Multi-attempt validation
- Proxy rotation
- 2FA handling
- Cookie management
```

### Account Validation
```python
# Recent additions
- Parallel validation
- Enhanced error handling
- Status tracking
- Recovery procedures
```

### WebSocket Integration
```python
# Implemented features
- Real-time status updates
- Connection management
- Error broadcasting
- Task progress tracking
```

## Current Focus Areas

### 1. Account Management
- Improving validation reliability
- Enhancing recovery procedures
- Optimizing proxy usage
- Strengthening error handling

### 2. Task Processing
- Refining rate limiting
- Enhancing batch processing
- Improving error recovery
- Optimizing resource usage
- Implemented task reassignment to original workers
- Added worker_account_id to Task model

### 3. System Reliability
- Strengthening error handling
- Improving retry mechanisms
- Enhancing monitoring
- Optimizing performance

## Known Issues

### 1. Password Management
- Occasional timeout issues during validation
- 2FA service reliability
- Proxy rotation edge cases
- Browser automation stability

### 2. Account Validation
- Rate limit handling edge cases
- Recovery success rate
- Proxy reliability issues
- Status synchronization

### 3. Task Processing
- Queue management under load
- Resource utilization
- Error recovery procedures
- Status update reliability

## Next Steps

### Immediate Priorities
1. Enhance password management reliability
   - Improve retry logic
   - Strengthen validation
   - Optimize proxy usage

2. Optimize account validation
   - Refine parallel processing
   - Enhance recovery procedures
   - Improve status tracking

3. Strengthen task processing
   - Enhance rate limiting
   - Improve batch handling
   - Optimize resource usage

### Future Enhancements
1. System Improvements
   - Enhanced monitoring
   - Better error tracking
   - Performance optimization
   - Scalability improvements

2. Feature Additions
   - Advanced task types
   - Enhanced analytics
   - Improved reporting
   - Better automation

3. Technical Debt
   - Code refactoring
   - Test coverage
   - Documentation updates
   - Dependency updates

## Development Notes

### Current Patterns
1. **Error Handling**
```python
try:
    # Operation logic
except PlaywrightTimeoutError:
    # Timeout handling
except Exception as e:
    # General error handling
finally:
    # Cleanup
```

2. **Retry Logic**
```python
for attempt in range(max_retries):
    try:
        # Operation
        break
    except Exception:
        if attempt == max_retries - 1:
            raise
        await asyncio.sleep(backoff_delay)
```

3. **Status Updates**
```python
await broadcast_message(request, "task_update", {
    "task_type": "validation",
    "status": "in_progress",
    "message": "Processing..."
})
```

### Best Practices
1. **Error Management**
   - Log all errors
   - Implement retries
   - Provide clear messages
   - Maintain state consistency

2. **Resource Handling**
   - Clean up resources
   - Manage connections
   - Handle timeouts
   - Monitor usage

3. **Status Tracking**
   - Real-time updates
   - Clear status messages
   - Error notifications
   - Progress tracking

This active context document reflects the current state of development and serves as a guide for ongoing work. It should be updated regularly as the project evolves.
