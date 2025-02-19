import React from 'react';
import { Tooltip, IconButton, Typography, Box } from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';

const HelpTooltip = ({ title, content, examples, placement = 'right' }) => {
  return (
    <Tooltip
      title={
        <Box sx={{ maxWidth: 300, p: 1 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1 }}>
            {title}
          </Typography>
          <Typography variant="body2" sx={{ mb: 1 }}>
            {content}
          </Typography>
          {examples && (
            <>
              <Typography variant="caption" sx={{ fontWeight: 'bold', display: 'block', mt: 1 }}>
                Example:
              </Typography>
              <Typography variant="caption" component="pre" sx={{ 
                whiteSpace: 'pre-wrap',
                backgroundColor: 'rgba(0, 0, 0, 0.1)',
                p: 1,
                borderRadius: 1,
                fontFamily: 'monospace'
              }}>
                {examples}
              </Typography>
            </>
          )}
        </Box>
      }
      placement={placement}
      arrow
    >
      <IconButton size="small" color="primary" sx={{ ml: 1 }}>
        <HelpOutlineIcon fontSize="small" />
      </IconButton>
    </Tooltip>
  );
};

export default HelpTooltip;
