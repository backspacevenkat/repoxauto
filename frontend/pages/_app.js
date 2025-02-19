import { WebSocketProvider } from '../components/WebSocketProvider';
import Layout from '../components/Layout';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { SnackbarProvider } from 'notistack';

// Create a theme instance
const theme = createTheme({
  palette: {
    mode: 'light',
    background: {
      default: '#f5f5f5'
    }
  },
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none'
        }
      }
    }
  }
});

function MyApp({ Component, pageProps }) {
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <SnackbarProvider maxSnack={3}>
        <WebSocketProvider>
          <Layout>
            <Component {...pageProps} />
          </Layout>
        </WebSocketProvider>
      </SnackbarProvider>
    </ThemeProvider>
  );
}

export default MyApp;
