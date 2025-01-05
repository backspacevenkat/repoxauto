import Layout from '../components/Layout';
import SearchPanel from '../components/SearchPanel';
import { Typography, Box, Container, Button, Stack } from '@mui/material';
import { History as HistoryIcon } from '@mui/icons-material';
import NextLink from 'next/link';

export default function Search() {
    return (
        <Layout>
            <Container maxWidth="xl">
                <Box sx={{ py: 4 }}>
                    <Stack 
                        direction="row" 
                        justifyContent="space-between" 
                        alignItems="center" 
                        mb={4}
                    >
                        <Box>
                            <Typography 
                                variant="h4" 
                                component="h1" 
                                gutterBottom
                                sx={{ fontWeight: 'bold' }}
                            >
                                Search Twitter
                            </Typography>
                            <Typography 
                                variant="subtitle1" 
                                color="text.secondary"
                            >
                                Search tweets, users, and trending topics. All searches are tracked as tasks.
                            </Typography>
                        </Box>
                        <NextLink href="/tasks" style={{ textDecoration: 'none' }}>
                            <Button
                                variant="outlined"
                                startIcon={<HistoryIcon />}
                            >
                                View All Search Tasks
                            </Button>
                        </NextLink>
                    </Stack>
                    <SearchPanel />
                </Box>
            </Container>
        </Layout>
    );
}
