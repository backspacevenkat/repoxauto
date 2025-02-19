import React, { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  CircularProgress,
  Alert,
  Grid,
  IconButton,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction
} from '@mui/material';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import DeleteIcon from '@mui/icons-material/Delete';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

export default function FollowListUploader() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [selectedFiles, setSelectedFiles] = useState({
    internal: null,
    external: null
  });

  const handleFileSelect = (type, file) => {
    if (!file) return;
    
    if (!file.name.endsWith('.csv')) {
      setError(`${type} list must be a CSV file`);
      return;
    }

    setSelectedFiles(prev => ({
      ...prev,
      [type]: file
    }));
    setError(null);
  };

  const handleUpload = async (type) => {
    const file = selectedFiles[type];
    if (!file) return;

    setLoading(true);
    setError(null);
    setSuccess(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const apiUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000') + '/api';
      console.log(`Uploading ${type} list:`, {
        url: `${apiUrl}/follow/upload/${type}`,
        fileName: file.name,
        fileSize: file.size,
        fileType: file.type
      });
      const response = await fetch(`${apiUrl}/follow/upload/${type}`, {
        method: 'POST',
        body: formData,
        mode: 'cors',
        headers: {
          'Accept': 'application/json',
        }
      });
      console.log('Upload response status:', response.status);
      console.log('Response headers:', Object.fromEntries(response.headers.entries()));

      const contentType = response.headers.get("content-type");
      console.log('Response content type:', contentType);

      if (!response.ok) {
        let errorMessage;
        try {
          console.log('Error response status:', response.status);
          console.log('Error response headers:', Object.fromEntries(response.headers.entries()));
          
          if (contentType && contentType.includes("application/json")) {
            const errorData = await response.json();
            console.log('Error response data:', errorData);
            errorMessage = errorData.detail || `Failed to upload ${type} list`;
          } else {
            const textResponse = await response.text();
            console.log('Error response text:', textResponse);
            try {
              // Try to parse as JSON even if content-type is not json
              const jsonData = JSON.parse(textResponse);
              errorMessage = jsonData.detail || textResponse;
            } catch {
              errorMessage = textResponse || `Failed to upload ${type} list`;
            }
          }
          console.log('Final error message:', errorMessage);
        } catch (parseError) {
          console.error('Error parsing response:', parseError);
          errorMessage = `Failed to upload ${type} list: Server error`;
        }
        throw new Error(errorMessage);
      }

      const result = await response.json();
      console.log('Success response:', result);
      
      let successMessage = `${type} list uploaded successfully: ${result.added_count} usernames added`;
      if (result.warnings) {
        successMessage += `\n${result.warnings}`;
      }
      setSuccess(successMessage);
      setSelectedFiles(prev => ({
        ...prev,
        [type]: null
      }));
    } catch (error) {
      console.error(`Error uploading ${type} list:`, error);
      setError(`Failed to upload ${type} list: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const clearFile = (type) => {
    setSelectedFiles(prev => ({
      ...prev,
      [type]: null
    }));
  };

  return (
    <Card>
      <CardContent>
        <Typography variant="h5" gutterBottom>
          Upload Follow Lists
        </Typography>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {success && (
          <Alert severity="success" sx={{ mb: 2 }}>
            {success}
          </Alert>
        )}

        <Grid container spacing={3}>
          <Grid item xs={12} md={6}>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  Internal List
                </Typography>
                
                <Box display="flex" alignItems="center" mb={2}>
                  <Button
                    variant="contained"
                    component="label"
                    startIcon={<CloudUploadIcon />}
                    disabled={loading}
                  >
                    Select File
                    <input
                      type="file"
                      hidden
                      accept=".csv"
                      onChange={(e) => handleFileSelect('internal', e.target.files[0])}
                    />
                  </Button>
                  
                  {selectedFiles.internal && (
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={() => handleUpload('internal')}
                      disabled={loading}
                      sx={{ ml: 2 }}
                    >
                      Upload
                    </Button>
                  )}
                </Box>

                {selectedFiles.internal && (
                  <List>
                    <ListItem>
                      <ListItemText 
                        primary={selectedFiles.internal.name}
                        secondary={`Size: ${(selectedFiles.internal.size / 1024).toFixed(2)} KB`}
                      />
                      <ListItemSecondaryAction>
                        <IconButton edge="end" onClick={() => clearFile('internal')}>
                          <DeleteIcon />
                        </IconButton>
                      </ListItemSecondaryAction>
                    </ListItem>
                  </List>
                )}
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={6}>
            <Card variant="outlined">
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  External List
                </Typography>
                
                <Box display="flex" alignItems="center" mb={2}>
                  <Button
                    variant="contained"
                    component="label"
                    startIcon={<CloudUploadIcon />}
                    disabled={loading}
                  >
                    Select File
                    <input
                      type="file"
                      hidden
                      accept=".csv"
                      onChange={(e) => handleFileSelect('external', e.target.files[0])}
                    />
                  </Button>
                  
                  {selectedFiles.external && (
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={() => handleUpload('external')}
                      disabled={loading}
                      sx={{ ml: 2 }}
                    >
                      Upload
                    </Button>
                  )}
                </Box>

                {selectedFiles.external && (
                  <List>
                    <ListItem>
                      <ListItemText 
                        primary={selectedFiles.external.name}
                        secondary={`Size: ${(selectedFiles.external.size / 1024).toFixed(2)} KB`}
                      />
                      <ListItemSecondaryAction>
                        <IconButton edge="end" onClick={() => clearFile('external')}>
                          <DeleteIcon />
                        </IconButton>
                      </ListItemSecondaryAction>
                    </ListItem>
                  </List>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>

        {loading && (
          <Box display="flex" justifyContent="center" mt={2}>
            <CircularProgress />
          </Box>
        )}

        <Box mt={2}>
          <Typography variant="body2" color="textSecondary">
            Note: Files must be CSV format with a 'username' column containing Twitter usernames.
          </Typography>
        </Box>
      </CardContent>
    </Card>
  );
}
