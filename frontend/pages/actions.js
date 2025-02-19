import React from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import ActionsPanel from '../components/ActionsPanel';
import { Box, Typography, Paper } from '@mui/material';
import InfoCard from '../components/help/InfoCard';
import HelpTooltip from '../components/help/HelpTooltip';

export default function Actions() {
  return (
    <Layout>
      <Head>
        <title>Actions - Xauto</title>
      </Head>

      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
          <Typography variant="h4" gutterBottom>Actions</Typography>
          <HelpTooltip
            title="Twitter Actions"
            content="Create and manage Twitter actions like likes, retweets, replies, quotes, and follows."
            examples="account_no,task_type,source_tweet,text_content\nWACC001,reply,https://x.com/user/status/123,Great point!"
          />
        </Box>

        <Paper sx={{ p: 3, mb: 3 }}>
          <InfoCard
            title="Action CSV Format"
            description="CSV format for bulk action creation. Each row represents one action to be performed."
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
              'Full CSV Format:\naccount_no,task_type,source_tweet,text_content,media,api_method,user,priority\nact203,like,https://x.com/user/status/123,,,graphql,,0\nact204,RT,https://x.com/user/status/123,,,rest,,0\nact205,follow,,,,graphql,elonmusk,0',
              '\nMinimal Follow Format:\naccount_no,task_type,user\nWACC162,follow,PayomDousti\nWACC163,follow,mogmachine'
            ]}
          />
        </Paper>
      </Box>

      <ActionsPanel />
    </Layout>
  );
}
