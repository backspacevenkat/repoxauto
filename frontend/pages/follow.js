import React from 'react';
import { Box, Container, Grid, Typography, Paper, Divider } from '@mui/material';
import Layout from '../components/Layout';
import FollowSettingsPanel from '../components/FollowSettingsPanel';
import FollowListUploader from '../components/FollowListUploader';
import FollowSystemStats from '../components/FollowSystemStats';
import FollowPipelinePanel from '../components/FollowPipelinePanel';
import HelpTooltip from '../components/help/HelpTooltip';
import InfoCard from '../components/help/InfoCard';

export default function FollowPage() {
  return (
    <Layout>
      <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4" gutterBottom>Follow System</Typography>
          <HelpTooltip
            title="Follow System"
            content="Manage Twitter following operations with rate limiting and scheduling. Upload internal (mutual) and external (target) follow lists."
            examples="username\nuser1\nuser2\nuser3"
          />
        </Box>

        <InfoCard
          title="Follow System Overview"
          description="The follow system manages Twitter following operations with rate limiting and scheduling. It supports both internal (mutual) and external (target) follow lists."
          requirements={[
            'Active worker accounts',
            'Valid follow lists',
            'Configured follow settings',
            'Available system resources'
          ]}
          validationRules={[
            'Maximum 400 follows per day',
            'Minimum 60 seconds between follows',
            'Following count between 300-400',
            'Maximum 3 schedule groups'
          ]}
        />

        <Grid container spacing={3}>
          {/* System Stats */}
          <Grid item xs={12}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="h6">System Statistics</Typography>
              <HelpTooltip
                title="System Stats"
                content="Real-time statistics showing follow system performance, rate limits, and account distribution."
              />
            </Box>
            <FollowSystemStats />
          </Grid>

          {/* Pipeline Panel */}
          <Grid item xs={12}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="h6">Follow Pipeline</Typography>
              <HelpTooltip
                title="Follow Pipeline"
                content="Monitor active follow operations, queued tasks, and completion status."
              />
            </Box>
            <FollowPipelinePanel />
          </Grid>

          {/* Settings Panel */}
          <Grid item xs={12}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="h6">Follow Settings</Typography>
              <HelpTooltip
                title="Follow Settings"
                content="Configure follow system behavior including limits, schedules, and distribution settings."
              />
            </Box>
            <FollowSettingsPanel />
          </Grid>

          {/* List Uploader */}
          <Grid item xs={12}>
            <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
              <Typography variant="h6">Follow Lists</Typography>
              <HelpTooltip
                title="Follow Lists"
                content="Upload and manage lists of Twitter users to follow. Supports both internal (mutual) and external (target) follow lists."
                examples="username\nuser1\nuser2\nuser3"
              />
            </Box>
            <FollowListUploader />
          </Grid>
        </Grid>

        {/* Detailed Instructions */}
        <Paper sx={{ mt: 3, p: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6" gutterBottom>
              How to Use
            </Typography>
            <HelpTooltip
              title="Usage Instructions"
              content="Step-by-step guide for using the follow system effectively."
            />
          </Box>

          <InfoCard
            title="Follow List Requirements"
            description="Requirements for preparing and uploading follow lists."
            requirements={[
              'CSV file with username column',
              'UTF-8 encoding',
              'Maximum 1000 usernames per file',
              'Valid Twitter usernames'
            ]}
            validationRules={[
              'No @ symbol in usernames',
              'One username per line',
              'No duplicate usernames',
              'Maximum file size: 1MB'
            ]}
            examples={[
              'username\nuser1\nuser2\nuser3'
            ]}
            templateUrl="/templates/follow_list_template.csv"
          />

          <Divider sx={{ my: 3 }} />

          <InfoCard
            title="Follow System Rules"
            description="System rules and limitations for following operations."
            requirements={[
              'Follow intervals: 15-minute minimum',
              'Daily limits: 30 follows per account',
              'Distribution: 5 internal, 25 external per day',
              'Following range: 300-400 accounts',
              'Schedule groups: 3 groups, 8-hour schedules',
              'Rate limiting: 15-minute pause when limited'
            ]}
          />
        </Paper>
      </Container>
    </Layout>
  );
}
