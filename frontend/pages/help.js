import React from 'react';
import {
  Container,
  Typography,
  Box,
  Tabs,
  Tab,
  Paper,
  Breadcrumbs,
  Link,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Divider
} from '@mui/material';
import {
  AccountCircle as AccountIcon,
  PlayArrow as ActionIcon,
  Task as TaskIcon,
  Person as ProfileIcon,
  Search as SearchIcon,
  Settings as SettingsIcon,
  Upload as UploadIcon,
  Error as ErrorIcon,
  Code as ApiIcon
} from '@mui/icons-material';
import Layout from '../components/Layout';
import InfoCard from '../components/help/InfoCard';

function TabPanel({ children, value, index, ...other }) {
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`help-tabpanel-${index}`}
      aria-labelledby={`help-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ py: 3 }}>{children}</Box>}
    </div>
  );
}

export default function HelpPage() {
  const [value, setValue] = React.useState(0);

  const handleChange = (event, newValue) => {
    setValue(newValue);
  };

  return (
    <Layout>
      <Container maxWidth="lg">
        <Box sx={{ mb: 4 }}>
          <Breadcrumbs aria-label="breadcrumb">
            <Link color="inherit" href="/">
              Dashboard
            </Link>
            <Typography color="text.primary">Help & Documentation</Typography>
          </Breadcrumbs>
        </Box>

        <Typography variant="h4" gutterBottom>
          Help & Documentation
        </Typography>

        <Paper sx={{ mt: 3 }}>
          <Tabs
            value={value}
            onChange={handleChange}
            indicatorColor="primary"
            textColor="primary"
            variant="scrollable"
            scrollButtons="auto"
          >
            <Tab icon={<AccountIcon />} label="Account Management" />
            <Tab icon={<ActionIcon />} label="Actions" />
            <Tab icon={<TaskIcon />} label="Tasks" />
            <Tab icon={<ProfileIcon />} label="Profile Updates" />
            <Tab icon={<SearchIcon />} label="Search Operations" />
            <Tab icon={<ApiIcon />} label="API Methods" />
            <Tab icon={<ErrorIcon />} label="Troubleshooting" />
          </Tabs>

          <TabPanel value={value} index={0}>
            <InfoCard
              title="Account Import"
              description="Import Twitter accounts in bulk using CSV files. Each account can be configured with proxy settings and custom user agents."
              requirements={[
                'CSV file with required columns',
                'UTF-8 encoding',
                'Maximum file size: 10MB',
                'One account per row'
              ]}
              validationRules={[
                'account_no must be unique',
                'login must be a valid Twitter username',
                'All proxy fields required if using proxy',
                'Valid email format required'
              ]}
              examples={[
                'account_no,login,password,email,proxy_url,proxy_port\nWACC001,user1,pass123,user1@email.com,proxy.example.com,8080'
              ]}
              templateUrl="/templates/accounts_template.csv"
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Account Types"
              description="Different types of Twitter accounts and their purposes."
              requirements={[
                'Normal accounts: Standard Twitter accounts',
                'Worker accounts: Dedicated for scraping operations',
                'Account status tracking',
                'Type-specific validation flows'
              ]}
              validationRules={[
                'Worker accounts need higher rate limits',
                'Normal accounts for regular operations',
                'Account type cannot be changed after creation',
                'Different validation rules per type'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Username Changes"
              description="Process for changing Twitter usernames and updating account records."
              requirements={[
                'Account must be active and validated',
                'New username must be available',
                'Account must not be rate limited',
                'Proper authentication tokens'
              ]}
              validationRules={[
                'Username must be 4-15 characters',
                'Only letters, numbers, and underscores',
                'Cannot start with a number',
                'No consecutive underscores'
              ]}
            />
          </TabPanel>

          <TabPanel value={value} index={1}>
            <InfoCard
              title="Action Types"
              description="Different types of Twitter actions and their requirements."
              requirements={[
                'Like: Target tweet URL required',
                'Retweet (RT): Source tweet URL required',
                'Reply: Tweet URL and reply text required',
                'Quote: Tweet URL and quote text required',
                'Follow: Target username required'
              ]}
              validationRules={[
                'Valid tweet URLs for tweet actions',
                'Text content within character limits',
                'Media URLs must be direct links',
                'Rate limit compliance required'
              ]}
              examples={[
                'account_no,task_type,source_tweet,text_content\nWACC001,reply,https://x.com/user/status/123,"Great point!"'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Action CSV Format"
              description="CSV format for bulk action creation."
              requirements={[
                'account_no: Account to perform action',
                'task_type: like, RT, reply, quote, post, follow',
                'source_tweet: Tweet URL for interactions',
                'text_content: For replies, quotes, posts',
                'media: Optional media URLs',
                'api_method: graphql or rest',
                'user: Required for follow actions',
                'priority: Optional (default: 0)'
              ]}
              examples={[
                'account_no,task_type,source_tweet,text_content,media,api_method,user,priority\nWACC001,like,https://x.com/user/status/123,,,graphql,,0'
              ]}
            />
          </TabPanel>

          <TabPanel value={value} index={2}>
            <InfoCard
              title="Task Types"
              description="Different types of automated tasks available."
              requirements={[
                'Profile scraping: Collect user information',
                'Tweet scraping: Collect user tweets',
                'Search tasks: Find tweets/users',
                'Trending topics: Monitor trends'
              ]}
              validationRules={[
                'Worker account required',
                'Valid parameters for task type',
                'Rate limit allocation',
                'Resource availability'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Task Parameters"
              description="Configuration options for different task types."
              requirements={[
                'Tweet count: 1-100 tweets per task',
                'Time range: 1-168 hours (1 week)',
                'Reply depth: 0-20 replies per tweet',
                'Search parameters: keywords, filters'
              ]}
              validationRules={[
                'Valid parameter ranges',
                'Resource limits',
                'Rate limit compliance',
                'Storage capacity'
              ]}
            />
          </TabPanel>

          <TabPanel value={value} index={3}>
            <InfoCard
              title="Profile Fields"
              description="Available Twitter profile fields and their requirements."
              requirements={[
                'Username: Twitter handle',
                'Display name: Profile name',
                'Bio: Profile description',
                'Location: Optional location',
                'Website: Optional URL',
                'Profile image: Avatar',
                'Banner image: Header image'
              ]}
              validationRules={[
                'Username: 4-15 chars, letters/numbers/underscores',
                'Display name: 1-50 chars',
                'Bio: 0-160 chars',
                'Location: 0-30 chars',
                'Website: Valid URL',
                'Images: JPG/PNG format'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Username Requirements"
              description="Specific requirements for Twitter usernames."
              requirements={[
                'Length: 4-15 characters',
                'Characters: Letters, numbers, underscores',
                'Start: Cannot begin with a number',
                'Format: No special characters'
              ]}
              validationRules={[
                'Must be unique on Twitter',
                'No consecutive underscores',
                'No reserved words',
                'Case insensitive'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Image Requirements"
              description="Requirements for profile and banner images."
              requirements={[
                'Profile: 400x400px JPG/PNG',
                'Banner: 1500x500px JPG/PNG',
                'Max size: 2MB for profile, 5MB for banner',
                'Direct image URLs required'
              ]}
              validationRules={[
                'Public image URLs',
                'Valid image format',
                'Correct dimensions',
                'File size limits'
              ]}
            />
          </TabPanel>

          <TabPanel value={value} index={4}>
            <InfoCard
              title="Search Operations"
              description="Different types of Twitter search operations."
              requirements={[
                'Tweet search: Find specific tweets',
                'User search: Find Twitter users',
                'Trending topics: Monitor trends',
                'Advanced search operators'
              ]}
              validationRules={[
                'Valid search syntax',
                'Rate limit compliance',
                'Result count limits',
                'Cache duration'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Search Parameters"
              description="Available parameters for search operations."
              requirements={[
                'Keywords and phrases',
                'Date ranges',
                'Language filters',
                'Location filters',
                'Result type filters'
              ]}
              validationRules={[
                'Valid date formats',
                'Supported languages',
                'Geographic bounds',
                'Filter combinations'
              ]}
            />
          </TabPanel>

          <TabPanel value={value} index={5}>
            <InfoCard
              title="API Methods"
              description="Different API methods available for Twitter operations."
              requirements={[
                'graphql: Modern Twitter API',
                'rest: Legacy Twitter API',
                'Method-specific parameters',
                'Different rate limit pools'
              ]}
              validationRules={[
                'graphql: 900 requests/15min',
                'rest: Method-specific limits',
                'Token requirements',
                'Error handling'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Rate Limits"
              description="Rate limiting rules for different operations."
              requirements={[
                'Account-specific limits',
                'Method-specific limits',
                'Window-based tracking',
                'Automatic backoff'
              ]}
              validationRules={[
                'Follow: 400/day, 50/hour',
                'Tweets: 900/15min window',
                'Search: 900/15min window',
                'Profile updates: 150/hour'
              ]}
            />
          </TabPanel>

          <TabPanel value={value} index={6}>
            <InfoCard
              title="Common Issues"
              description="Solutions for common problems and error scenarios."
              requirements={[
                'Account validation failures',
                'Rate limit errors',
                'API errors',
                'Task failures'
              ]}
              validationRules={[
                'Check account status',
                'Verify rate limits',
                'Validate parameters',
                'Review error logs'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Error Resolution"
              description="Steps to resolve common errors."
              requirements={[
                'Rate limits: Wait or use different account',
                'Auth errors: Refresh cookies/tokens',
                'Task errors: Check parameters',
                'API errors: Verify request format'
              ]}
              validationRules={[
                'Follow retry procedures',
                'Check system resources',
                'Verify configurations',
                'Monitor error patterns'
              ]}
            />

            <Divider sx={{ my: 3 }} />

            <InfoCard
              title="Best Practices"
              description="Recommended practices for optimal system operation."
              requirements={[
                'Regular account validation',
                'Proper rate limit management',
                'Task parameter optimization',
                'Resource monitoring'
              ]}
              validationRules={[
                'Follow Twitter guidelines',
                'Monitor success rates',
                'Optimize resource usage',
                'Regular maintenance'
              ]}
            />
          </TabPanel>
        </Paper>

        <Box sx={{ mt: 4, mb: 2 }}>
          <Typography variant="h6" gutterBottom>
            CSV Templates
          </Typography>
          <List>
            <ListItem>
              <ListItemIcon><UploadIcon /></ListItemIcon>
              <ListItemText
                primary={
                  <Link href="/templates/accounts_template.csv" download>
                    Account Import Template
                  </Link>
                }
                secondary="CSV template for importing Twitter accounts"
              />
            </ListItem>
            <ListItem>
              <ListItemIcon><UploadIcon /></ListItemIcon>
              <ListItemText
                primary={
                  <Link href="/templates/follow_list_template.csv" download>
                    Follow List Template
                  </Link>
                }
                secondary="CSV template for follow operations"
              />
            </ListItem>
            <ListItem>
              <ListItemIcon><UploadIcon /></ListItemIcon>
              <ListItemText
                primary={
                  <Link href="/templates/profile_updates_template.csv" download>
                    Profile Updates Template
                  </Link>
                }
                secondary="CSV template for updating Twitter profiles"
              />
            </ListItem>
          </List>
        </Box>
      </Container>
    </Layout>
  );
}
