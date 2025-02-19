import React from 'react';
import {
  Card,
  CardContent,
  Typography,
  Box,
  Divider,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Button,
  Collapse
} from '@mui/material';
import {
  Info as InfoIcon,
  Warning as WarningIcon,
  CheckCircle as CheckIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Download as DownloadIcon
} from '@mui/icons-material';

const InfoCard = ({
  title,
  description,
  requirements = [],
  validationRules = [],
  examples = [],
  templateUrl,
  expanded = false
}) => {
  const [isExpanded, setIsExpanded] = React.useState(expanded);

  return (
    <Card sx={{ mb: 2, border: '1px solid', borderColor: 'divider' }}>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center' }}>
            <InfoIcon color="primary" sx={{ mr: 1 }} />
            <Typography variant="h6" component="div">
              {title}
            </Typography>
          </Box>
          <Button
            size="small"
            onClick={() => setIsExpanded(!isExpanded)}
            endIcon={isExpanded ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          >
            {isExpanded ? 'Show Less' : 'Show More'}
          </Button>
        </Box>

        <Typography variant="body2" color="text.secondary" paragraph>
          {description}
        </Typography>

        <Collapse in={isExpanded}>
          {requirements.length > 0 && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
                Requirements
              </Typography>
              <List dense>
                {requirements.map((req, index) => (
                  <ListItem key={index}>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <CheckIcon color="success" fontSize="small" />
                    </ListItemIcon>
                    <ListItemText primary={req} />
                  </ListItem>
                ))}
              </List>
            </>
          )}

          {validationRules.length > 0 && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
                Validation Rules
              </Typography>
              <List dense>
                {validationRules.map((rule, index) => (
                  <ListItem key={index}>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <WarningIcon color="warning" fontSize="small" />
                    </ListItemIcon>
                    <ListItemText primary={rule} />
                  </ListItem>
                ))}
              </List>
            </>
          )}

          {examples.length > 0 && (
            <>
              <Divider sx={{ my: 2 }} />
              <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
                Examples
              </Typography>
              {examples.map((example, index) => (
                <Box
                  key={index}
                  sx={{
                    backgroundColor: 'grey.100',
                    p: 1,
                    borderRadius: 1,
                    mb: 1,
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap'
                  }}
                >
                  <Typography variant="caption" component="pre">
                    {example}
                  </Typography>
                </Box>
              ))}
            </>
          )}

          {templateUrl && (
            <>
              <Divider sx={{ my: 2 }} />
              <Button
                variant="outlined"
                startIcon={<DownloadIcon />}
                href={templateUrl}
                download
                size="small"
              >
                Download Template
              </Button>
            </>
          )}
        </Collapse>
      </CardContent>
    </Card>
  );
};

export default InfoCard;
