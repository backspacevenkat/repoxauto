import Layout from '../components/Layout';
import ProfileUpdatesPanel from '../components/ProfileUpdatesPanel';
import { Box, Typography, Paper, Divider } from '@mui/material';
import HelpTooltip from '../components/help/HelpTooltip';
import InfoCard from '../components/help/InfoCard';

export default function ProfileUpdates() {
  return (
    <Layout>
      <Paper sx={{ p: 4 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
          <Typography variant="h4" gutterBottom>Profile Updates</Typography>
          <HelpTooltip
            title="Profile Updates"
            content="Update Twitter profiles in bulk by uploading CSV files. Supports updating names, descriptions, locations, and profile images."
            examples="account_no,name,description,url,location\nWACC001,John Doe,Bio text,https://example.com,New York"
          />
        </Box>

        <InfoCard
          title="Profile Update System"
          description="The profile update system allows you to modify Twitter profile attributes in bulk. You can update display names, bios, locations, URLs, and profile images."
          requirements={[
            'CSV file with required columns',
            'Direct image URLs for profile/banner',
            'Valid field lengths',
            'UTF-8 encoding'
          ]}
          validationRules={[
            'Name: max 50 characters',
            'Description: max 160 characters',
            'Location: max 30 characters',
            'URL: valid web address',
            'Images: direct JPG/PNG URLs'
          ]}
          examples={[
            'account_no,name,description,url,location,profile_image\nWACC001,John Doe,Bio text,https://example.com,New York,http://img.url/pic.jpg'
          ]}
          templateUrl="/templates/profile_updates_template.csv"
        />

        <Divider sx={{ my: 3 }} />

        <InfoCard
          title="Field Requirements"
          description="Specific requirements for each profile field."
          requirements={[
            'account_no: Required, must match existing account',
            'name: Display name (max 50 chars)',
            'description: Bio text (max 160 chars)',
            'url: Valid website URL',
            'location: Location string (max 30 chars)',
            'profile_image: Direct JPG/PNG URL',
            'profile_banner: Direct JPG/PNG URL',
            'lang: ISO language code (e.g., en, es)'
          ]}
        />
        
        <Box mt={4}>
          <ProfileUpdatesPanel />
        </Box>
      </Paper>
    </Layout>
  );
}
